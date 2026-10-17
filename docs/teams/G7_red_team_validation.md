# G7 — Red Team, Validation & Research

*Working Group G7 (second wave), ApexOptions design team. Session held Saturday 17 October 2026 (IST), after reading in full: `00_CONTEXT_PACK.md`, the six first-wave memos G1–G6, `02_DECISION_LOG.md` (D-001…D-030) and `03_OPEN_QUESTIONS.md`. MYTHOS figures are taken as verified from the brief (361 trades, −355.5 pts, −₹3,29,492, 41% win, +4.3/−4.7, median peak +3.1, 163/361 time-based exits, 8 of 31 days positive); we did not re-derive them.*
*Tags: **[FACT]** verified in a memo's cited source, code or arithmetic shown here · **[OWNER]** the owner's words · **[ANALYSIS]** our reading · **[HYPOTHESIS]** must be tested before it is trusted.*

---

## 0. Members and their lenses

- **Dr. Ravi Shankar** — skeptical quant: overfitting, multiple comparisons, power on 30 frame-days and 15 shadow sessions, sequential tests (SPRT), pre-registration.
- **Catherine Dubois** — ex-prop-desk risk officer: how live-order systems actually lose money; what she would refuse to let go live; rails versus preferences.
- **Tobias Richter** — QA / failure-mode analyst: silent failures, custom-protocol risk, test oracles, what "fool-proof" can mean in engineering.
- **Anita Krishnan** — MYTHOS forensic auditor: catches every place the new design quietly rebuilds lateness, rule accretion, confirmation gates, hypotheses shipped as facts and display-only intelligence.

**Recorded disagreements (not resolved by vote; presented to the owner):**
1. *Day-stop.* Catherine: a hard rail, not switchable during validation phases. Anita: the mandate has no day-stop; the team presents and the owner decides. **Outcome:** §2(g) splits rails into three classes; the day-stop is an owner-switchable default, but the *phase size cap* (1 lot until the bar is met) is a hard rail because it protects the validation, not the trader.
2. *Custom socket.io client first or SDK first.* Tobias and Ravi: record the first probe on the SDK path with a raw-packet hook; build the custom client only behind a parity test. G5 and D-004 decided the reverse. **Outcome:** we reopen D-004 (§2e).
3. *Minimal first trigger.* Ravi: ship one 3–4-parameter trigger and earn every addition by ablation. Anita: a futures-momentum trigger is exactly MYTHOS's "ignition" engine (−138.5 pts out of sample, brief §3.3); minimal must not mean "the thing that already failed". **Outcome:** the minimal trigger must beat an ignition-style matched null, not merely zero (§4.7).
4. *Signal-driven one lot before the shadow bar.* Catherine: execution failures are only learnable live and one lot is cheap; allow it. Ravi: that is "live creep", the six-rebuilds pattern. **Outcome:** the *owner-clicked* execution trial (G6 §6.3) happens early and is signal-free; *signal-driven* one-lot trading waits for the shadow SPRT (§4).

---

## 1. Per-group critique

### G1 — Domino & Lag

**Strongest claims.** (i) No market-maker delta-repricing lag is capturable by a retail buyer (quotes reprice in "~10–100 ms"; our path is "hundreds of milliseconds") — **[ANALYSIS]**, falsifiable by probe P1(3). (ii) The cash print is a lagging indicator and never a trigger input — sound, adopted. (iii) Lead claims are bounded by vendor skew between NSE cash and NFO: "nothing shorter than ~2× that skew may be claimed as a lead" — the best methodological line in the six memos. (iv) §5.10's confirmation-entry arithmetic reproduces MYTHOS's median peak +3.1 — a falsifiable explanation of MYTHOS's loss as timing rather than direction.

**Where it could be late again.** FALLING requires *six* simultaneous conditions (S ≥ 0.5, B ≥ 0.5, |z_b| ≥ 2, futures ≥ 3 pts in 5 s, S′ ≥ 0.35, c < 0.6) on a 15-s membership window. That is an AND-gate whose median time-to-satisfy is unknown; G1 itself says if median L_p at trigger exceeds ~0.5 "we have rebuilt MYTHOS with better vocabulary". That number must be the first output of F4. **[ANALYSIS]**

**Where it could be wrong with confidence.** "Too late" = L_p ≥ 0.6 **or any two of {L_r, L_iv, L_v, print caught up}** — a 2-of-4 vote, contradicting D-015's "never a k-of-n vote". L_p depends on k_proj = 2.0 (range 1.5–3.0), learned from the same frames the trigger is evaluated on; lateness is defined by a fitted number with "wide error bars". The F3 bar compares the domino entry to "the confirmation entry" (+2 pts better): beating a known loser is not an edge. **[ANALYSIS]**

**Hidden assumptions.** The frames carry 14 heavyweights (~62% of weight per G1), HDFCBANK dead before ~23 Jun, sisters at 20-s REST, no stock futures, no BankNifty futures — so F1 on frames cannot see the bank-led episodes G1 most expects and sees synchrony on two-thirds of the basket. A frames "pass" is weak evidence for the live 50-name detector. **[FACT, G1 §6.1]**

**Wrong prior carried.** §5.10 costs theta "over 3 min ≈ 1–1.5 pts". At G4's 0.03–0.15 pt/min that is 0.1–0.45 pts. Numerically minor, but the memo carries the discredited prior. **[ANALYSIS, §2c]**

**Rule-accretion risk.** ~26 tunables (the §5.13 list of 16 plus entry |z_b| 1.5, clear 0.5/10 s, quiet 0.5/30 s, G < −5 invalidation, 40% reversal, print-caught-up 0.8/0.5, lead margin 0.05, σ half-life 20 min). F4 sweeps them on ~20 days and tests once on ~10. **[ANALYSIS]**

**Cut:** HRY/Hasbrouck nightly diagnostics (research, not product); the lead table on screen until P1 skew ≤ 300 ms; `asks_pulled` urgency (D-016 says the lead is unproven). **Keep without reservation:** print-is-never-an-input; F1 with its 15% re-scope rule; the matched null in F2; episode classification as *annotation*; 09:15–09:25 suppression as a measured limit.

### G2 — Pressure Zones

**Strongest claims.** (i) "Pressure" decomposes into resistance R and fuel U in one unit, so R/F is a time — a definition, not a claim. (ii) Wind as a CUSUM on one flux with amplifiers, not a vote — the right statistical shape. (iii) The "variant — late because the tell came by REST" is the clearest demonstration in any memo of how MYTHOS entered late. (iv) Study C's bar (median lead ≥ 20 s before a 25-pt break, AUC ≥ 0.65 OOS) is falsifiable.

**Wrong prior, with a false conclusion built on it.** §5.6 uses θ_min = 0.3 pt/min and, for expiry Tuesday 14:30, "θ_min can be 1–1.5 … M_req balloons to ~60 and most sails fail the pays rule after lunch — which is the owner's expiry caution made numeric." At G4's 0.15–0.25 pt/min, θ·H over 13 min is ~2–3 pts, not 15–20, and M_req stays near 25–30. The "expiry caution made numeric" is an artefact; expiry-afternoon refusal must come from G4's delta bands and risk-per-point table, not from G2's pays rule. **[ANALYSIS; correction proposed as D-031]**

**Wrong book.** §5.2 attributes ρ = 0.4, π = 0.35 to "asks at 23,100 CE being pulled". Per D-012 those quantities live on the Nifty-futures book; and per G3 five levels are a quarter-point window, so a depth-pull amplifier at "the wall ahead" is measurable only once the touch is *at* the wall — it cannot be an early amplifier. **[ANALYSIS]**

**Hidden assumptions.** The wall-unwind amplifier ("OI at the wall ahead falling ≥ 2%/min") presumes tick-cadence OI — unmeasured (D-018). Hedger, covering and stop fractions h, c, f are "fitted constants" 30 sessions cannot identify. Study A's bar ("hold rate distinguishable from 50%") uses the wrong null: the control is the hold rate of *random price levels* matched for distance and approach speed. **[ANALYSIS]**

**Rule accretion and display-only risk.** ~38 tunables (wall 2.0×, h, c, f, λ_b, λ_s, profile decay 0.7/5 sessions, void 0.3×, five amplifier thresholds and five gains, three φ weights, k, h, two resets, κ, leg cap, IV cap, α, break 25 pts/60 s, decay 8%/day, 10-day eviction, OR 15 min, half-width). Amplifier gains multiply to 1.5³ × 1.25² ≈ 5.3×, so five weak cues can manufacture a crossing. The R/U field, GEX, max pain, sister fields and basket overlay reach the decision only through "destination exists" — a beautiful screen that may not change P&L, which is MYTHOS's display-only intelligence. **[ANALYSIS]**

**Cut from v1:** rejection sails (doubles the trigger surface; MYTHOS's bounces were its losers); GEX and max pain; the basket-overlay field; U in any formula; wall-unwind and depth-pull amplifiers until the probe. **Keep without reservation:** the zone ledger with tests held/broken (cheap; G3 needs a level registry); leg-consumed and IV-rise caps as *lateness* tests; Study A with a corrected null; the "first ~100 pts of a 155-pt trip" sail window as an owner-readable concept.

### G3 — Order-book Force & Flow

**Strongest claims.** (i) Five levels at ₹0.05 = a quarter point: a microscope on the touch, not a wall map **[arithmetic]**. (ii) Per-level differencing manufactures a false pull on every quoter re-price; S/R/P are window totals (D-013). (iii) Broker feeds are 1–4 snapshots/s with a 250 ms floor — the owner's "number of sellers falling" is a snapshot series with a known bias. (iv) The negative control against MYTHOS's BOOK ignition (1,104 events in one replay; −48.2 OOS) is exactly the right instinct.

**Where it could be late again.** BREAK-IMMINENT requires ρ_10s < 0.5 sustained ≥ 2 snapshots *and* ≥ 2 s, S < 0.4·S₀, A ≥ baseline, π ≥ 0.3, strike OI not rising over 60 s, K_d ≥ 0.7, *and* G1 basket sign agreeing — seven conjunctive clauses including a 60-s OI window and a cross-group dependency. G3 §5.8 says the sure version "is MYTHOS again". The answer is WEAKENING (~50% false positives) for "pre-positioning" — but G6 maps `urgency = rest` to a *real resting limit at ask − 1 tick*. A signal designed to be wrong half the time must not place orders in v1. **[ANALYSIS]**

**Hypotheses posing as structure.** Run-score weights 0.3/0.3/0.3/0.1, v_ref 0.5 pt/s, rate-class cut-offs ±0.15/0.30/0.40/0.50, attack bands, floors (100/50/200/50 lots), iceberg 3×, spoof 10× — tagged hypothesis, correctly — ~42 tunables in all. **[ANALYSIS]**

**Internal inconsistency.** Calibration needs "≥ 150 labelled tests per class per regime"; the bar is "≥ 10 live sessions" and "≥ 150 labelled Nifty-futures tests". At G3's 20–40 tests/day, 150 tests is ~5 sessions; 150 *per class per regime* (HOLD/BREAK × expiry/non-expiry × VIX bands) is 30–60 sessions. The bar must say which. **[ANALYSIS]**

**Cut from v1:** WEAKENING-driven orders; the "OI not rising" clause until the OI probe; spoof/iceberg detectors (display only); the G1 sign inside BREAK-IMMINENT (fusion belongs in one place, not inside a verdict). **Keep without reservation:** tick classification with an explicit U bucket; per-instrument trade/book/feed staleness; "no verdict (stale)" instead of a last value; the recorder column list (the best spec in the six memos); the latency–accuracy curve with the owner choosing the operating point.

### G4 — Options, Greeks & Instrument Selection

**Strongest claims.** (i) Theta is 0.03–0.15 pt/min, not 0.3–1.5; the 5-minute bleed is vega and spread (D-019). (ii) Θ/Γ = −F²σ²/2 for every strike at the same IV: a gamma/theta ranking only re-ranks the smile — an identity **[FACT]**. (iii) Under all-in sizing *strike choice is position sizing*; risk per adverse spot point ≈ Δ/P × utilisation; the lot-count table is the single most useful page for the owner. (iv) greeks.py's spot-intrinsic bug for ITM puts **[FACT, code]**.

**New correction — the time clock is inconsistent.** The speed ratio uses M_be = F·σ·√(H/525,600), i.e. *calendar* minutes; theta is "per trading minute = Θ_day/375". Two clocks. If intraday variance is booked in trading time, the 5-minute 1σ move at 13% IV and Nifty 23,000 is 23,000 × 0.13 × √(5/94,500) ≈ **21.7 pts**, not 9.2 (252 × 375 = 94,500 trading minutes a year). The truth lies between (overnight gaps carry some variance), but the ρ thresholds (refuse < 1.0, strong ≥ 1.5) move by up to 2.4× with the convention. One variance clock must be chosen and calibrated on the frames' realised 5/10-minute moves before ρ is shown, let alone used. **[ANALYSIS; proposed D-032]**

**Where it could be wrong with confidence.** LATE = any two of four IV tests — another 2-of-4 vote. The behavioural PIN regime gates approval on G3 BREAK-IMMINENT — gate stacked on gate. The instrument score (Δ/P efficiency − spread − vega penalty − charm penalty + "already moving" bonus) has unspecified weights and is "live from day one" (D-021/D-023) because "it delays nothing"; it does not delay, but it changes P&L — a hypothesis shipped live. **[ANALYSIS]**

**Exit rule accretion.** Structural stop, % cap, take-zone, R:R gate 1.5, trail from +1R, thesis-void, bleed-exceeded with W extension, move-happened-IV-deflated (three thresholds), vega windfall (two), 0DTE W cap, 0DTE flat 15:00, no entries after 14:45: twelve exit rules. MYTHOS had ~15. G4 deleted the four worst (+3 floor, breakeven ratchet, 4-minute kill, clock exits) — real progress — but is rebuilding the ladder under better names. **[ANALYSIS, Anita]**

**Cut from v1:** the scoring function (replace with: DTE delta band → nearest-the-money strike passing the spread filter); GEX in any form; windfall and IV-deflated exits until the frames IV-path study shows their sign and size; the bleed rule until m_emp exists. **Keep without reservation:** the Black-76 forward-based rewrite; delta bands as de-leveraging rules; 0DTE ITM-only and no entries after 14:45; trail on the futures path; "no clock-only exit, ever"; the trigger card in ₹, premium points and spot points side by side.

### G5 — Data Platform & Latency

**Strongest claims, all verified in source [FACT]:** the SDK spawns a thread per message (~100 µs), gives no ordering guarantee, hides every connect error behind one string, never closes the socket in `ws_disconnect`, truncates `ltt` via `strftime('%c')`, and calls REST with no `Session` or timeout. The measured 12–18 µs hot path, the seqlocked table, the sequenced per-socket recorder, "the first tick is the only truth about a subscription", unlimited in-hours reconnects, the 18-row watchdog table and the TLS diagnosis (the saved `cert.pem` is UTF-16, leaf-only and could not have fixed 16 Oct) are excellent.

**Hidden assumptions and traps.** (i) The custom socket.io client's shape canary checks *message* shape; the real risk is the *handshake* (`40{auth}` payload, headers, query parameters reverse-engineered from the SDK). If ICICI changes it, the custom client fails at 09:15 with nothing to compare against. (ii) The economics: ~100 µs per tick is irrelevant against a 100–400 ms vendor path; what matters is ordering and `ltt` resolution, both recoverable without owning the protocol (record raw packets in the engine.io receive loop before dispatch). (iii) Three sockets on one session is unmeasured (stage D); design for one, upgrade to three. (iv) The preflight (§5.9) has no public-IP-vs-registered-static-IP check (G6 has one), and the REST table still budgets "limit price & qty calculator — sizing per entry, 15/day", which D-024 showed is an OptionPlus calculator. **[ANALYSIS]**

**Rule accretion:** none in the decision sense; scope risk high (≈300–360 feeds, ~100 of them Tier-1 stock options no trigger uses). **Cut from v1:** Tier-1 stock options; Tier-2 promotion; the Parquet shredder; the second browser socket until the fat-frame test fails on one. **Keep without reservation:** process isolation, shared table, recorder, watchdogs, TLS probe, REST ledger, lockstep replay, fault-injection matrix, the on-screen meter with its honest "EXCH→FEED ≈ 0–1 s".

### G6 — Execution, Risk & Capital

**Strongest claims.** Static IP is mandatory, with the literal rejection string **[FACT, ICICI FAQ]**; `fnolmtpriceandqtycal` is the OptionPlus calculator **[FACT]**; the SDK "market" order is LTP ± 10% after a hidden quote call and `modify_order` reads before it writes **[FACT, SDK]**; SL-M is gone for options, so the protective order is SL-limit **[FACT]**; no intraday auto-square-off for the API's product; Kelly is negative at MYTHOS's statistics (f* ≈ −0.24); F&O allocation = day's capital turns ICICI's funds check into a physical duplicate guard. The two invariants in G6 §2 are the right framing.

**Errors and contradictions.** (i) "Freeze slicing is implemented but unreachable at ₹1 lakh" is wrong: 54 lots × 65 = 3,510 units costs ₹1,00,000 at a premium of **₹28.5**, and ₹1,30,000 at **₹37**. G4's own table lists 58- and 86-lot positions. D-009 then says sizing is "*capped* by freeze qty", which would silently violate all-in. Slicing must be built and exercised live. **[FACT, arithmetic]** (ii) The daily 09:16 probe buys at ₹0.05: below the contract's lower operating band it can be exchange-rejected rather than `Ordered`, proving IP and auth but not the order socket. Price it at `max(lowerCktLm, 0.05)` and define pass as "order id plus an `Ordered` notification, then `Cancelled`". **[HYPOTHESIS]** (iii) Whether ICICI's RMS treats a pending SL sell against a long as a square-off or a fresh short needing margin is the single assumption dead-session protection rests on; at 94% utilisation a margin-requiring SL is rejected and the position is naked to a dead session. We make it a go/no-go gate (§6). (iv) The ladder chases to ask + 2–3 pts over three IOC rungs in 4 s; the all-in quantity walks depth, so shadow P&L must model that walk at all-in size while live is one lot. **[ANALYSIS]**

**Cut:** nothing material. **Keep without reservation:** IOC entries, one protective order modified into the exit, UNKNOWN → query-never-resend, intent book vs broker book, the manual checklist ordering (cancel the SL before selling), the risk tables, paper-through-real-path as one code path.

### The decision log (D-001…D-030), attacked

| Decision | Verdict | Why |
|---|---|---|
| D-004 own socket.io client | **REOPEN** | Decided before the probe that should decide it. Probe on SDK + raw hook; custom client only after a full-session parity test (§2e). |
| D-009 "capped by freeze qty" | **CORRECT** | Slice, never cap; reachable below ₹28.5–37 premiums. |
| D-010 flat by 15:25 everywhere | **AMEND** | 0DTE flat by 15:00 unless Δ ≥ 0.9 (G4) must be an invariant on expiry day, not a G4 preference. |
| D-014 WEAKENING lets G4/G6 pre-position | **AMEND** | Pre-position = compute contract and size only; no resting order on WEAKENING in v1. |
| D-015 "never a k-of-n vote" | **CORRECT** | G1's too-late and G4's LATE are 2-of-4 votes. Either one composite score or admit the vote and count its tunables. |
| D-016 MM-lag correction | **ACCEPT, keep MEASURE** | The probe must close it; until then `asks_pulled` is display-only. |
| D-019 theta correction | **ACCEPT + EXTEND** | G1 §5.10 and G2 §5.6 still carry the old prior (D-031); G4's own clock is inconsistent (D-032). |
| D-021 selector live day one | **AMEND** | Live as a rule (band + spread filter), not as the unweighted score. |
| D-022 exit geometry | **AMEND** | v1 exit set limited to four rules (§4.7); the rest shadow-logged. |
| D-027 ≥10–15 shadow sessions | **AMEND** | Replace session counts by an SPRT on trades plus day-level conditions (§4). 15 sessions is a kill test with ~25–40% power, as G1 admits. |
| D-029 probe on a normal and an expiry day | **ACCEPT, re-date** | Mon 19 Oct is the expiry day and needs no custom client: record it. |

---

## 2. Cross-group contradictions — adjudicated

**(a) MM repricing lag: G1 "none capturable" vs "MMs pull asks before the level gives way" (G1-Anja §3, brief §5.5, G2's amplifier, G1's urgency).**
**DECISION now:** no part of the design may depend on an MM lead; `asks_pulled` is display-only and may not set urgency. **MEASUREMENT (probe days 1–2):** for every Nifty-futures mid change ≥ 2 pts, the delay to the first hero-option mid change of the Δ-implied sign (distribution, in snapshots and ms); for every hero-ladder "asks thin + bids build" event, P(futures moves ≥ 5 pts in d within 30 s) against the unconditional base rate at the same time of day. If the median option response is within one snapshot of the futures move, the delta-lag question is closed for good. `asks_pulled` earns urgency only with lift ≥ 1.5× base rate over ≥ 100 events and a day-clustered 95% CI above 1.0. **[ANALYSIS]**

**(b) ρ/π on a CE book (G2) vs the futures book (G3).** Settled by D-012 (futures). Residual: G2 §5.2 and its depth_pull amplifier are rewritten against the futures book; depth-pull can fire only during a test (touch within ±5 futures pts), never "ahead". The option ladder supplies K_d and the run score only. **DECISION.**

**(c) Theta prior 0.3–1.5 vs 0.03–0.15.** G4 is right (D-019). Still carrying the wrong prior: **G2 §5.6** (θ_min 0.3 in the main example; 1–1.5 on expiry with a false conclusion) and **G1 §5.10** (1–1.5 pts per 3 min). G3, G5, G6 do not use theta. **DECISION:** both corrected (D-031). **MEASUREMENT:** G4's straddle-decay study yields m_emp by DTE × hour; the same study settles the clock (D-032) by comparing realised 5/10-min absolute futures moves to M_be under both clocks.

**(d) G6's corrections.** `fnolmtpriceandqtycal`: G5's REST table relies on the wrong reading — strike it; affordability from `get_funds`. Static IP mandatory: G5's preflight omits the IP check — add it; the brief's framing ("whether this applies … is an open question") is superseded. No other memo depends on either. **DECISION.**

**(e) G5's custom socket.io client.** **DECISION:** a trap as a day-one dependency; justified as a later optimisation. Sequence: (1) probe on the SDK path with a raw-packet hook in the engine.io receive loop that records bytes + `recv_ns` *before* the thread-per-message dispatch — true arrival order and raw epoch `ltt` without owning the protocol; (2) build the custom client; (3) **parity test** — both clients on the same 10 hero tokens for a full session on separate sockets (only after stage D shows two sockets are allowed): every (token, ttq, last, bid, ask, OI) tuple seen by one is seen by the other; pass = ≥ 99.9% tuple match, zero tokens silent on one side, zero ttq regressions on the custom side, connect-failure reasons visible; (4) **fallback** — automatic, not a flag: after two consecutive handshake failures the FEED relaunches on the SDK path and alarms "PROTOCOL FALLBACK"; the SDK path is exercised in preflight every morning so it cannot rot. **[ANALYSIS]**

**(f) OI per trade vs per interval.** **MEASUREMENT (probe 1):** per NFO quote message log raw OI, ttq, recv_ns; compute (1) fraction of messages where OI changed; (2) fraction of OI changes coincident with Δttq > 0; (3) the distribution of intervals between OI changes per contract; (4) WS OI vs REST chain OI at the same strike, and the lag. **Outcomes:** *O1 — OI changes with trades, sub-second:* the wall-unwind amplifier may enter G2's wind gain after Study C shows it leads; G3 may test its "OI not rising" clause. *O2 — OI changes on a fixed interval (tens of seconds to minutes):* OI is context only; every OI feature uses a horizon ≥ 3 intervals; G2's "OI −2.4%/min on the WS field" example is illegitimate; G3 drops the clause. *O3 — OI static intraday on WS:* OI from REST only; walls are a 90-s map. In all three cases OI is never a trigger input in v1 (consistent with D-018).

**(g) Day-stop / 3-stop pause / 6–8% cap vs all-in.** One page the owner signs, three classes:
- **Invariants (not switchable):** no naked short; one position; protective order on every fill; time rails; order-rate and REST limits; kill switch; and the *phase size cap* (0 lots in shadow, 1 lot in trial, ramp steps) — because it protects the measurement, and the owner's own record ("six rebuilds, each shipped live unproven") is the reason.
- **Owner-switchable defaults (on unless he says off, logged):** day-stop X = 20% (G6); 3-stop / 30-min pause (G6); the per-trade cap as a *strike-eligibility filter* (G4) — it never reduces lots, it only removes contracts whose structural stop would cost more than 6–8% of capital, so it is compatible with all-in.
- **Information only:** the streak table (48% of 12-trade days at 41% win contain a 4-loss run), the gap-through table (−37% at P = 80), the Kelly sign.
Catherine's dissent stays in the record: at MYTHOS's statistics she would not let X be switched off. **[OWNER decides]**

---

## 3. What "fool-proof" can and cannot mean

**It cannot mean** profitable; filled at the expected price in a gap or an empty expiry-afternoon book; protected when NSE, ICICI's RMS or the owner's line is down; free of losing days; or safe against a signal with negative expectancy — only a pre-committed kill rule protects against that. It cannot mean bug-free. **It can mean** that every known failure class is caught by an invariant check before it costs money, and that the system fails *stopped and loud*, never *running and quiet*.

**The invariants.** Each is a testable property with an automated test in the paper-through-real-path harness and a live check; a violation blocks new entries and alarms.

| # | Invariant | Live check |
|---|---|---|
| I-1 | At most one open position and at most one live order of ours per side, ever. | pre-send; every notification |
| I-2 | Σ live sell quantity ≤ held long quantity at every instant (no naked short). | pre-send; notification cross-check cancels any excess sell |
| I-3 | Every filled unit is covered by exactly one resting protective sell (exchange SL-limit, or GTT if the trial proves SL-limit unusable) within 2 s of the fill; otherwise flatten immediately and HALT. | timer from first fill notification |
| I-4 | No entry unless: session heartbeat < 90 s, order socket alive, today's static-IP check passed, L1 age < 500 ms, contract = computed expiry with a non-empty chain, lot and freeze read from today's contract file. | local pre-trade checklist |
| I-5 | An order in UNKNOWN is resolved by query before any new order on that contract; nothing is re-sent blind. | state machine |
| I-6 | ≤ 3 order requests/s; ≤ 400 order calls/day; data lane ≤ 60 REST/min; order lane always holds 40/min and 300/day; no new entry when < 50 order calls remain. | token bucket + ledger |
| I-7 | No new entries after 15:15; flat by 15:25 (15:00 for 0DTE contracts unless Δ ≥ 0.9); alarm and checklist if not flat 2 min later. | clock rail |
| I-8 | Order quantity ≤ owner's formula ≤ broker-reported available funds; above freeze it is sliced, never capped. | sizing function |
| I-9 | Every value carries its age; no decision uses an input older than its horizon; stale means "no decision", never the last value. | per-input age gate |
| I-10 | Every order traces to a decision row with reason string, inputs hash, config version and code hash. | audit writer |
| I-11 | Live and shadow run the same code path; thresholds change only between sessions via a versioned config with a pre-registration note; no intraday edits. | config hash on every decision |
| I-12 | Kill switch reaches HALTED and starts the exit ladder within 2 s from any state; re-arm needs an explicit owner action. | daily dry run |
| I-13 | The lot cap per validation phase is enforced in code; changing it needs an owner-signed log entry citing the bar that was met. | phase file read at arm |
| I-14 | Alarms reach the owner without the browser (supervisor audio + toast). | preflight audio test |
| I-15 | No credential-shaped string in the tree; preflight refuses GO otherwise. | preflight scan |

"Which actually takes a trade" adds one *positive* invariant (from G6): **a decided trigger becomes an order within 100 ms unless an invariant above blocks it, and the block reason is on screen within 1 s** — measured daily as decisions → orders with every gap explained.

---

## 4. Validation protocol (pre-registered, whole system)

### 4.1 Common rules (every phase)
- **Unit of evidence:** net premium points per trade by honest fills — buy at the ask observed at *trigger time + measured ack latency*, walking the visible L5 ladder for the **all-in quantity** (shadow simulates all-in size even when live is one lot); sell at the bid likewise; minus G6's charge formula at the simulated lot count. Frames (no depth) add a fixed 0.5 pt per side for the walk.
- **Day-level conditions:** leave-one-day-out (every LODO mean > 0), drop-best-day total > 0, no single day > 40% of the total, ≥ 50% of days net-green (MYTHOS: 8/31).
- **Split:** by session in time order; nothing shuffled; thresholds frozen and hashed before any held-out run.
- **Multiplicity:** one primary hypothesis and one primary metric per subsystem, registered now; any further sweep is exploratory and cannot clear a bar.
- **Kill rule (owner pre-commits):** a failed bar retires that role (trigger → annotation); a retune is a *new* hypothesis tested only on sessions recorded *after* it.

### 4.2 Phase 1 — the 30+ MYTHOS frame days (kill tests only)
The frames (1–2 s, intra-frame order lost, no depth, 14 heavyweights ≈ 62% weight, sisters at 20 s, no stock or BN futures) **can** test: G1 F1/F2 on futures vs the 14-name basket (±2 s); G1 F3 premium capture with frame bid/ask; G4's m_emp, IV path after up/down impulses, and the clock; G2 Study A on 90-s chain walls and prior-day/profile levels, Study C at tens of seconds; G3's L1-only baseline and the BOOK-ignition negative control. They **cannot** test depth, ρ/π, order counts, sub-2-s leads, vendor skew, BN-/stock-futures leads, OI tick behaviour, fill quality or the all-in walk.

| Subsystem | Primary metric | Pass | Power caveat |
|---|---|---|---|
| G1 | F1 basket-led share; F3 absolute net at 180 s on the held-out third | ≥ 15%; mean net > 0 **and** ≥ +1 pt above an ignition-style matched null (same futures move, synchrony < 0.3); LODO; median L_p at trigger ≤ 0.5 | ~10 held-out days detect only effects ≳ 1.5 pt/trade |
| G2 | Study A hold rate vs random-level control; Study C lead and AUC; Study E sail expectancy | control-adjusted difference, 95% CI excluding 0; median lead ≥ 20 s and AUC ≥ 0.65 OOS; E per G2 §6.3(iii) | GEX/max pain not testable on ~15 expiries |
| G3 | L1 run score vs BOOK-ignition control | beats the control on the 30-s forward move, else the L1 path is dropped | says nothing about the depth detector |
| G4 | m_emp; IV-path sign; clock; each veto's gain and recall loss | tables produced; each veto ≥ +1.5 pt/trigger with ≤ 25% of top-quartile winners vetoed | four vetoes → Bonferroni |

**Passing proves** the idea is not dead on low-resolution history in one low-VIX regime. **It does not** prove anything live, and it does **not** shorten Phase 3 (Anita's condition).

### 4.3 Phase 2 — tick-recorder observe period
**≥ 10 sessions of raw recording**, including Mon 19 Oct (weekly expiry), Tue 27 Oct (monthly expiry), at least one **trend day** (|close − open| ≥ 1.0% of Nifty) and one **range day** (high − low < 0.6× the 20-day median range); extend until both occur. Pass: recorder drops = 0; silent subscribed instruments = 0 after fixes; feed→paint p50 ≤ 10 ms / p99 ≤ 30 ms; every probe fact in §6 written down; ≥ 150 labelled Nifty-futures level tests for G3 (fewer → G3 stays display-only). No trades; no threshold tuned before session 5.

### 4.4 Phase 3 — shadow trading, real order path disabled
Executor on G6's FillSimulator against the live book; every subsystem runs; only the minimal trigger (§4.7) plus components that cleared Phase 1 are "wired". **Primary test — Wald SPRT on per-trade net points**, σ frozen from the frames' per-trade SD (illustrated at σ = 6; MYTHOS's win/loss means alone give a lower bound of 4.4): H0 μ ≤ 0 vs H1 μ ≥ +1.5, α = 0.05, β = 0.20. With n trades and cumulative net Σx:
- **GO line:** Σx ≥ 66.5 + 0.75·n
- **KILL line:** Σx ≤ −37.4 + 0.75·n
- expected trades to decide ≈ 61 if μ = +1.5, ≈ 43 if μ = 0; truncated at 200 trades (undecided = fail).
Plus the §4.1 day-level conditions, ≥ 15 sessions, ≥ 2 expiry days, ≥ 1 trend day. **Proves:** under the assumed variance the edge is unlikely to be ≤ 0 at live cadence with the all-in walk modelled. **Does not prove** its size (95% CI half-width at 60 trades ≈ ±1.5 pts), execution, or regime robustness. Trades within a day are correlated — hence the mandatory day-level conditions.

### 4.5 Phase 4 — live, one lot
(a) **Owner-clicked execution trial** (G6 §6.3), signal-free, as soon as a static IP exists — gates in §6. (b) **Signal-driven, one lot**, after the Phase 3 GO: ≥ 30 trades and ≥ 10 sessions; median |simulated − real fill| ≤ 0.3 pt, p95 ≤ 1.0 pt (G6); live net per trade within 1 pt of shadow net on the same days; the SPRT continues on live trades and its KILL line still applies; zero invariant violations. **Proves** the paper model is honest. **Does not prove** all-in fills (one lot does not walk the book; the shadow walk model does).

### 4.6 Phase 5 — bar for enabling all-in
All of: Phase 3 GO; Phase 4b passed; zero execution incidents in the last 10 sessions; the rails page (§2g) signed. Ramp 25% → 50% → 100% of the all-in quantity, ≥ 3 sessions per step; any incident or two day-stop hits → back one step. The owner may shorten the ramp; under I-13 he may not skip Phase 3.

### 4.7 Over-parameterisation and the minimal first trigger
**Count [ANALYSIS, our tally of each memo's thresholds and weights]:** G1 ≈ 26, G2 ≈ 38, G3 ≈ 42, G4 ≈ 30 (with exits) → **≈ 136 signal tunables**, plus ≈ 14 execution parameters (calibrated by fills, not P&L). Data: frames ≈ 300–900 impulse events at low resolution; recorded depth **zero** today; a 15-session shadow at ≤ 8 triggers/day yields ≤ 120 trades. A held-out decision needs ~10–20 events per free parameter, so 120 trades support **5–10 parameters**. The fused design is over-parameterised by roughly **15–25×** and cannot be validated in 2026 as written.

**Minimal first trigger — four tunables, the only thing wired in Phase 3:**
1. **Impulse:** Nifty-futures 15-s move in direction d with z ≥ m* against its own 20-min scale.
2. **Structure:** G1 weighted synchrony S(15 s) ≥ s* across the tracked basket.
3. **Not late (one composite):** futures move since episode onset ≤ L* × its 20-min median impulse (no k_proj), and ATM IV up ≤ 1.5 vol pts since onset (G2's cap, frozen, not tuned).
4. **Exits:** exchange SL at a fixed spot distance d* converted by Δ; trail on the futures path from +1R; thesis-void = synchrony sign flip; the time rail. Nothing else.
Instrument: DTE delta band, nearest-the-money strike passing the spread filter. Everything else (G2 sail, G3 verdicts, G4 vetoes, domino classification) runs **advisory, with a "would-have" verdict logged on every trigger**, and is wired only after an add-one ablation on shadow data shows ≥ +1 pt/trade improvement with ≤ 25% loss of top-quartile winners. The trigger must beat Anita's null — a MYTHOS ignition-style entry on the same days — not merely zero.

---

## 5. Top failure modes, ranked

| # | Failure | How it happens | Detection | Rail | Owner |
|---|---|---|---|---|---|
| 1 | **Negative-edge signal at all-in size** | thresholds fitted to 30 days of one regime; MYTHOS repeated | SPRT KILL line; day-level conditions | I-13 phase cap; kill rule | G7 / owner |
| 2 | **Static-IP mismatch, day one** | dynamic home line; every order "Request Denied" while data flows | preflight public-IP check; 09:16 probe | I-4: no arm without IP pass | G6 |
| 3 | **Dead session with an open position** | token expires/invalidated; `subscribe_feeds` returns strings | 120-s heartbeat, order-socket age, three-stage detector | exchange SL from fill (I-3); audio + checklist | G6 / G5 |
| 4 | **SL-limit rejected or margin-blocked** | RMS treats a pending sell as a fresh short at 94% utilisation | rejection notification within 1 s | I-3 → flatten + HALT; GTT after trial | G6 |
| 5 | **Unfilled stop in a vacuum / gap-through** | SL triggers, limit above every bid; expiry afternoons | SL triggered, not executed | active exit to band edge; a −30 gap = 24–37% of capital, bounded only by strike choice | G6 / G4 |
| 6 | **Duplicate order after timeout** | ack lost; retry re-sends | UNKNOWN state; intent vs broker book | I-5; allocation ceiling; IOC entries | G6 |
| 7 | **Wrong expiry Mon 19 Oct** | "next Tuesday" = 20 Oct (holiday, no contract); or the post-15:30 roll must go to Tue 27 Oct (monthly) | preflight prints expiry + chain row count; first-tick watchdog | NO-GO on empty chain; I-4 | G5 |
| 8 | **Lot or freeze change** | lot review for contracts after the Oct monthly expiry; freeze revised four times in 2026 | contract file per contract every morning | I-8; refuse to arm on a stale file | G6 / G5 |
| 9 | **Freeze reached as capital compounds** | premium < ₹28.5 (₹37 at ₹1.3 L) in expiry week → "Freezed" | rejection status | slicer live-tested in the trial | G6 |
| 10 | **Sale proceeds not reusable intraday** | T+1 release; allocation = capital blocks the second trade | `get_funds` after each exit vs ledger | sizing reads broker funds; BLOCKED with reason | G6 / owner |
| 11 | **EOD flatten too late** | 15:20 exit into a thin book; OTM 0DTE lapses | position non-zero at 15:25 | I-7 (0DTE flat by 15:00); alarm + checklist | G6 / G4 |
| 12 | **REST budget exhausted when an exit needs REST** | retry bug or poller storm; exits are modifies | ledger burn-rate projection | I-6 order-lane reserve; no entries < 50 order calls | G5 / G6 |
| 13 | **Depth socket silently lagging** | broker-side queueing on the hero socket at the open | futures canary across sockets; `recv − ltt` creep; depth `time` vs recv | entries blocked when lag > 1 s; "BROKER LAG" | G5 |
| 14 | **TLS intermediate missing again** | next leaf re-issue (current leaf expires 29 Apr 2027); `livefeeds` order socket separately | 5-s TLS probe on every connect failure; expiry countdown | `truststore` + pinned chain; order socket in preflight | G5 |
| 15 | **Custom client handshake breaks at 09:15** | ICICI changes auth or query parameters | handshake failure reason | automatic SDK fallback after two failures; SDK path exercised daily | G5 |
| 16 | **Stale value read as live** | frozen REST chain, silent instrument, background tab | ages; signature watchdog | I-9 | G5 / G3 |
| 17 | **Manual double-exit** | owner sells in the app while the SL rests | notification of a sell we did not send | checklist: cancel SL first; I-2 cancels excess | G6 / owner |

---

## 6. Build order and gates

| Step | When | Builds | Gate |
|---|---|---|---|
| 0 | Sat 17–Sun 18 Oct | **Probe recorder only:** SDK path with a raw-packet hook (bytes + `recv_ns` before dispatch), sequenced log, holiday-aware expiry function (19 Oct this week; 27 Oct after 15:30 Monday), token builder, TLS probe, credential store | dry run on a converted MYTHOS day; expiry function unit-tested for 19/20/21/27 Oct, 9/10 Nov, 23/24 Nov |
| 1 | **Mon 19 Oct** (expiry) | **First live probe** (checklist below) | `probe_report_1.md`: every item measured or marked "not observed" |
| 2 | Wed 21 Oct | Probe 2: multi-socket stage D, slot-hold stage G, join/leave timing, SDK vs custom A/B if built | two-socket answer; slot-hold seconds |
| 3 | from 19 Oct | G5 steps 0–2, 4–6 (table, FEED, GATEWAY + meter, replay, REST ledger, supervisor, preflight with IP check) | G5 acceptance tests; fault-injection matrix |
| 4 | parallel | Frames studies (§4.2) | kill tests vs the pre-registration |
| 5 | parallel | G6 executor + FillSimulator + invariant tests | G6 §6.2 suite; 20 paper sessions, zero invariant violations |
| 6 | once static IP exists | **Owner-clicked one-lot execution trial** (G6 §6.3) | go/no-go: IOC accepted on NFO options; SL-limit accepted *without* short margin (else GTT accepted and reconciled); modify works; proceeds reusable (or owner informed); session-kill drill: alarm ≤ 2 min and SL survives at NSE; freeze slicer exercised (2 slices of 1 lot) |
| 7 | after ≥ 5 observe sessions | Minimal trigger + advisory subsystems in shadow | Phase 3 SPRT |
| 8 | after Phase 3 GO | Signal-driven one lot | Phase 4b |
| 9 | after Phase 4b | Ramp | Phase 5 |

**First live probe — Monday 19 October 2026 (weekly expiry; Tue 20 Oct is Dussehra).**
- *Before 09:00:* session; TLS probe on `livestream` and `livefeeds`; clock vs the API `Date`; expiry = 19-Oct-2026 with a non-empty chain for both rights; tokens resolved; disk. Decide with the owner whether MYTHOS runs that day: if it does, the probe is a second socket on the same session and stage D happens implicitly (question 3 in §8).
- *Subscribe on one socket:* Nifty spot; Nifty near futures quotes + depth; BankNifty spot (CNXBAN) and an attempt at BankNifty futures; 19-Oct weekly ATM±8 both rights quotes, depth on ATM±2 (10 heroes); 27-Oct ATM±2 both rights quotes; the ten Tier-1 cash names and their near futures; INDVIX on WS (attempt). ≈ 85 feeds. At 10:00 add the remaining Nifty-50 cash names and record the rate change.
- *Log:* every raw packet with `recv_ns` and per-socket sequence; every REST call (VIX 1/min, Nifty chain every 90 s) with request and response times.
- *Measure:* msgs/s per instrument and type in 1-s bins (09:15–09:17 and 15:00–15:30 peaks); raw `ltt` type and resolution; out-of-order `ttq`; the four OI statistics (§2f); `CHNGOI` content; non-zero NFO depth order counts; depth `time` advancing without trades; depth `flag` contents; option-quote response to futures moves (§2a); `asks_pulled` lift; `totalSellQ` vs Σ visible asks; expiry-afternoon spreads and depth at ITM1/ITM2 from 13:00 (for G4's 0DTE rules); hero-set silence episodes; reconnects with reasons.
- *Not on Monday:* extra sockets beyond the implicit one, unclean kills, the custom client, any order call.

**Must NOT be built until a specific measurement exists:**
- G2 wall-unwind amplifier, G3 "OI not rising", any OI in φ → **OI cadence (probe 1)**.
- G3 verdict thresholds → **≥ 150 labelled futures tests on recorded depth**.
- G1 first-mover claims and lead table → **cash/NFO skew ≤ 300 ms (probe 1)**.
- `asks_pulled` urgency → **lift ≥ 1.5× over ≥ 100 events**.
- Three-socket split → **probe 2 stage D**.
- Custom socket.io client in production → **parity test**.
- G4 speed ratio as a gate → **clock calibration**; bleed rule → **m_emp**; vega exits → **frames IV-path study**.
- GTT path → **trial shows SL-limit unusable**.
- Any all-in order → **Phase 5**.
- *Must be built early, contrary to G6:* the freeze slicer, exercised in the one-lot trial.

---

## 7. MYTHOS trap check

| MYTHOS pattern | G1 Domino | G2 Pressure | G3 Force | G4 Greeks | G5 Platform | G6 Execution |
|---|---|---|---|---|---|---|
| Confirmation gates → late | **At risk** (6-way AND at FALLING; 15-s window) | **At risk** (SAIL = ALL of 6) | **Repeating** in BREAK-IMMINENT (7 clauses incl. 60-s OI); WEAKENING is the honest escape | **At risk** (PIN gate needs a G3 verdict) | Free | Free (IOC; no resting below LTP) |
| Exit rule accretion | Free (hands off) | Free (hints only) | Free | **At risk** (12 exit rules) | Free | Free (one order object) |
| Hypotheses shipped live | Free (bar §6.7) | Free (bar §6.3) | **At risk** (WEAKENING → resting order) | **Repeating** (selector score live day one) | **At risk** (custom client decided pre-probe) | Free (trial first) |
| Display-only intelligence | At risk (lead table, HRY) | **Repeating** (R/U field, GEX, max pain, overlay, sisters) | At risk (spoof/iceberg) | At risk (GEX panel) | Free | Free |
| Heavyweights as a sentiment blend | **Free** — Nifty points, own-baseline volume, ex-leader breadth | At risk (overlay via λ_b) | Free | Free | Free | Free |
| Six rebuilds without proof | Guarded only if the owner pre-commits to the kill rule in §4.1. The memo set itself (~48k words, ~136 tunables) is the "add more brains" reflex — Anita's strongest objection. | | | | | |

Anita's summary: the design is *free* of MYTHOS's specific mechanics (the +3 floor, the 4-minute kill, print-based zone entries, waiting for OI-writing events) but *at risk* of its meta-pattern — answering uncertainty with more modules. The minimal trigger and the ablation rule in §4.7 are the antidote.

---

## 8. Top ten open questions only the owner can answer

Merged with `03_OPEN_QUESTIONS.md`. **Promoted:** OQ-9 (measurement first) into Tier A and re-dated to Monday; OQ-3 (proceeds) stays Tier A. **New:** questions 1, 3, 5 and the ICICI half of 6. **Demoted:** OQ-4 (certificate forensics) to Tier B — `truststore` and the probe make the answer non-blocking; OQ-12 (frames use) to Tier C — already assumed; OQ-11 (rejection sails) — answered by the team: out of v1.

1. **Kill rule (new, first).** Will you pre-commit that if the shadow SPRT crosses the KILL line, the trigger is retired rather than retuned on the same days — and that any retune is tested only on sessions recorded after it?
2. **Static IP (OQ-1).** Is a static IP declared on the API key? Is your home line static? If not: ISP add-on (recommended) or cloud executor.
3. **Monday 19 Oct (new + OQ-9).** May the probe record Monday's expiry session? Will MYTHOS run that day on the same API key (making the probe a second socket), or will you pause it?
4. **Rails page (OQ-2).** Day-stop X (default 20%), the 3-stop pause and the 6–8% strike-eligibility cap: on, changed or off — and do you accept the phase size cap as non-negotiable?
5. **Presence (new).** On live days, will you be at the screen all session? A dead session with a position needs a human; if not, the trading window shrinks to the hours you are present.
6. **Proceeds and stop margin (OQ-3 + new).** Are sale proceeds reusable intraday in your ICICI account? Can you ask ICICI whether a pending SL-limit sell against a long option is margined as a square-off?
7. **Exit geometry (OQ-5).** Do you accept v1's four exits (structural SL, futures trail from +1R, thesis-void, time rail), with premium points shown on the card?
8. **Expiry afternoons (OQ-8).** Next week's contract preferred after 13:00 on expiry day, 0DTE only at Δ ≥ 0.8, none after 14:45, 0DTE flat by 15:00?
9. **Vetoes (OQ-10).** Agree that no veto blocks an order until it has cleared its own ablation bar?
10. **The domino you have watched (OQ-6):** the usual first mover and the timescale, so F1 looks for the right events.

---

## 9. One-paragraph summary for the master design

G7's verdict: the platform (G5) and execution layer (G6) come close to fool-proof in the only sense the word can carry — explicit, testable invariants that make the system fail stopped and loud. The decision layer (G1–G4) is honest about its uncertainty but, taken together, repeats the MYTHOS meta-pattern. It has about 136 tunable thresholds against at most ~120 shadow trades and zero recorded depth. Its "not-a-vote" gates are AND-gates or 2-of-4 votes (G1 too-late, G3 BREAK-IMMINENT, G4 LATE). G1 and G2 still carry the wrong theta prior, and G2's "expiry caution made numeric" is an artefact of it. G4's speed ratio mixes calendar and trading minutes (9.2 vs 21.7 pts for a 5-minute 1σ move at 13% IV). G6's claim that the freeze quantity cannot be reached is false below a ₹28.5 premium. And D-004 chose a custom socket.io client before the probe that should decide it. We therefore propose six steps. First, record Monday 19 Oct's expiry session on the SDK path with a raw-packet hook. Second, build the platform, executor and invariants. Third, run the owner-clicked one-lot execution trial as soon as a static IP exists, with SL-limit margin treatment as a go/no-go gate. Fourth, wire one four-parameter trigger in shadow (futures impulse, basket synchrony, a single lateness test, four exits), tested against a pre-registered SPRT: GO when Σx ≥ 66.5 + 0.75n, KILL when Σx ≤ −37.4 + 0.75n, with leave-one-day-out checks and the all-in depth walk modelled. Fifth, keep every other subsystem advisory until it earns its place by ablation. Sixth, move to one live lot and then the all-in ramp only through the phase gates in §4, under a kill rule the owner commits to before the first shadow trade.
