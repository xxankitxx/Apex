# G6 — Execution, Risk & Capital

*Working Group G6 of the ApexOptions design team. Written Saturday 17 Oct 2026. Chair: G6 lead. Tags as in the brief: **[FACT]** verified in code/docs/circulars (sources cited), **[OWNER]** the owner's words, **[ANALYSIS]** our reading, **[HYPOTHESIS]** must be tested before trusted.*

---

## 1. Members and their lenses

- **Rajesh Pillai** — execution trader, Indian index options: how a 10–19-lot buy actually fills on a Nifty weekly, spread behaviour during a burst, stop fills on gaps, expiry-day books.
- **Chen Wei** — broker-API integration: the Breeze order lifecycle as the SDK really implements it, idempotency, notification streams, what breaks at 09:15.
- **Dr. Amara Nwosu** — risk mathematics: ruin and drawdown under all-in compounding, Kelly versus full stake. Informs the owner; never overrides him.
- **Deepak Varma** — compliance/operations: SEBI's 2025 retail-algo framework, static IP, order-rate limits, audit trail, runbooks.

---

## 2. What we were asked

**[OWNER]** *"sits in with 1 lakh a day, go all in everytime it takes a trade. Use the profits and again go all in when it takes another trade and so on."* · *"I will only buy options. I will not sell them. Which is even more dangerous."* · *"a fool proof system (which actually takes a trade)."*

**[ANALYSIS] Our reading.** The sizing rule is decided; our job is to execute it exactly and show the arithmetic. "Fool proof" for the execution layer means two invariants, both enforceable in code:

1. **Never miss a trade the system decided to take** because of execution: a trigger must become a filled position unless a hard rail (funds, band, freeze quantity, halted state, market closed) says no — and then the owner sees *why* within a second.
2. **Never hold a position the owner did not intend:** no duplicate buys, no naked short (a sell quantity that exceeds the long, ever), no wrong contract, no position without a resting protective order, no position the broker knows about and we do not.

Everything below serves those two invariants plus the owner's sizing rule. The previous system never placed an order (brief §3.1) — this layer is greenfield.

---

## 3. Ideas by member

**Rajesh Pillai (execution).**
- At ₹1 lakh the all-in quantity is 7–19 lots (455–1,235 units). On ATM/ITM-1 Nifty weeklies during a move the best ask typically shows thousands of units; this is a *taker* size. Lift the ask with a small buffer; do not rest below the market on a momentum entry. The old 5-second resting limit below LTP (`ENTRY_LIMIT_WAIT_SEC`) was a built-in delay on exactly the entries that needed speed.
- Use **IOC** entries: the remainder dies at the exchange — no cancel calls, no forgotten resting order that fills five minutes later on the way down.
- A stop-loss limit order needs a *limit cushion* below the trigger (5 points or ~4% of premium) or it becomes an unfilled stop on the first fast print. MYTHOS's worst recorded stop fill was −29 (config comment, **[FACT]**).
- ITM strikes (G4's preference, Δ 0.6–0.8) have thinner books; 780 units may walk 2–4 bid levels. G4 must see "absorbable quantity within 2 points" from the depth feed before choosing a strike. Expiry afternoons: bids vanish between prints; the cushion must widen.

**Chen Wei (broker integration).**
- The SDK's `place_order(order_type="market")` is not a market order: it makes an extra `get_quotes` REST call, then submits a limit at LTP ± 10% (minimum 5 points) clamped to the circuit limits (`get_aggressive_limit_price`, SDK 1.0.69 source **[FACT]**). Never use it: an extra round trip, priced off a REST LTP rather than our tick.
- `modify_order` in SDK 1.0.69 first calls `get_order_detail` and refuses unless status ∈ {ordered, requested, partially executed}; `square_off(order_id=…)` also reads first (**[FACT]**, SDK source). Every "one action" is two calls. The order path gets our own thin REST client (same auth headers, one HTTP call per action, persistent TLS session).
- Order notifications arrive on a **separate socket** (`livefeeds.icicidirect.com`, event `order`), not the price socket, and need `ws_connect()` first (**[FACT]**, SDK). The F&O message carries `orderReference, orderStatus, orderFlow, limitRate, orderTotalQuantity, executedQuantity, cancelledQuantity, expiredQuantity, stopLossTrigger, averageExecutedRate, strikePrice, expiryDate, optionType` (**[FACT]**, SDK `parse_data`, message types 6/7) — no `user_remark`, no explicit `order_id`; matching is by `orderReference` (**[HYPOTHESIS]** that it equals the `order_id` from `place_order`).
- Idempotency: Breeze has no client-order-id; `user_remark` (alphanumeric, echoed in the order list) is ours. Unknown state after a timeout → query, never blindly re-send.
- Make the broker's F&O fund allocation equal the day's capital, so ICICI's own funds check physically rejects a duplicate or oversized buy.

**Dr. Amara Nwosu (risk).**
- "All-in" on premium is not "all-in" on risk. With a stop at S premium points on a P-premium option, risk per trade ≈ S/P of capital: 8% at P=120/S=10, 12.5% at P=80. The ruin path is not the normal stop; it is the gap-through (−30 fill = 24–37%) and the streak.
- Kelly at MYTHOS's measured stats (p=0.41, win 4.3, loss 4.7) is **negative** (f* = 0.41 − 0.59/0.915 = −0.24): no stake size is right until the edge is positive. At the hoped-for 55% / +12 / −10, f* = 0.55 − 0.45/1.2 = 0.175; all-in at P=120 with a −10 stop (8%) is then roughly half-Kelly. The sizing rule is therefore *not* reckless if the edge exists and stops fill; it is fatal if the edge is MYTHOS's.
- Present the streak probabilities and the day-stop trade-off; recommend that the owner choose a day-stop X and a consecutive-stop pause, with defaults filled in.

**Deepak Varma (compliance/ops).**
- SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025) and NSE implementation standards NSE/INVG/67858 (5 May 2025) **[FACT]**: the threshold is **10 orders per second per exchange/segment**, counted on the broker server's calendar second; below it, no algo registration, but a **static IP is mandatory** for client-generated algos, non-registered algos run through **one** API key, and all algo orders are tagged by the broker with an exchange-provided generic algo ID. Above it: the broker must reject the orders (ICICI FAQ: "Your orders will be rejected").
- ICICI FAQ **[FACT]**: "A primary static IP is mandatory"; secondary optional; change once per week; the error for a mismatch is literally *"Request Denied: The IP address used does not match with the static IP declared when this API key was created."* The owner's home connection is probably dynamic — this is the single most likely reason day one places no order.
- Audit trail: the broker must keep 5 years (NSE/INVG/67858 §I.a); we keep our own, forever, append-only.
- Our executor needs its own rate limiter (hard 3 order requests/second, a per-day cap) so a bug can never reach the 10 OPS line or the 5,000/day budget.

---

## 4. The debate

**D1 — "Buy cheap" versus lift the ask.** The owner's historical preference (brief §1.4) was a brief resting limit below LTP. Rajesh: on a VACUUM/BREAK trigger a resting bid is a free option to the market — it fills when the move fails and misses when it works (adverse selection); MYTHOS's "knife guard" code is the symptom. Chen: resting orders also need cancels, which cost calls and create unknown-state windows. **Evidence that settles it:** fill rate and 1-minute mark-out of resting vs lifted entries on the paper-through-real-path mode (§6). **Decided:** default is IOC at ask+buffer; a sub-ask resting limit only when G3 sends `urgency = rest` (WEAKENING stage), with a TTL, and it is cancelled the moment the verdict upgrades.

**D2 — Re-price by modify or by cancel-and-replace.** Chen: modify keeps the broker's funds block and the order id (no window where funds are blocked by a dying order and the replacement is rejected for insufficient funds — real with 94% utilisation). Rajesh: with IOC entries the question disappears for entries; for exits, the resting stop is the object that must be re-priced. **Decided:** entries are IOC (no re-price of a resting order; a new IOC at the next rung). Exits re-price the single resting sell by **modify** through our own one-call client. Cancel-then-IOC is the fallback if the one-lot trial shows modify is unreliable.

**D3 — Dead-session protection: exchange stop-loss order or broker GTT.** Both exist in Breeze **[FACT]**: `place_order(order_type="stoploss", stoploss=<trigger>, price=<limit>, validity="day")` (documented order types "limit","stoploss"; NSE discontinued SL-M for options on 27 Sep 2021 and kept SL-limit) and `gtt_single_leg_place_order(... gtt_type="single", order_details=[{"action":"sell","limit_price","trigger_price"}])` documented on NFO NIFTY options. Rajesh: the exchange order is held at NSE and fires at the trigger print; GTT is a broker-server condition with an unknown evaluation cadence. Chen: GTT does not appear in the normal order book and needs separate reconciliation; also unknown whether ICICI's RMS treats a sell SL against a long as a square-off (no short margin) — **[HYPOTHESIS]** for both. Deepak: one resting protective order is auditable; two can double-exit into a naked short. **Decided:** exchange SL-limit is the primary protective order, placed within one second of the fill; GTT is the fallback if the SL-limit is rejected or margin-blocked in the one-lot trial; **never both at once**.

**D4 — Daily hard stop.** Amara: at P=120, three consecutive −10 stops already cost 22%; a day-stop at −25% ends the day on the fourth. Rajesh: for a system whose only measured win rate is 41%, −25% is loose; −15% ends the day on the second stop, which the owner may find intolerable. The sizing is the owner's; the stop is the owner's. **Decided:** present X as a parameter with the table (§5.11); our default proposal is **X = 20%** of start capital plus a **30-minute pause after 3 consecutive stops**; both switchable off by the owner in config, logged as his decision.

**D5 — Where the executor runs.** Deepak: the static-IP rule may push the executor to a cloud VM (ICICI even publishes a GCP how-to). Chen/Rajesh: a cloud hop adds 20–60 ms each way and a second failure domain; the tick path (G5) is local. **Decided:** executor local, static IP from the ISP (business/static-IP add-on); cloud executor only if the ISP cannot provide one. Evidence: the owner's ISP options (§9).

**D6 — Is `fnolmtpriceandqtycal` an affordability calculator?** The brief (§2.1) lists it as one. Evidence against: the SDK README's documented response is `available_quantity: '0', order_margin: '0', limit_rate: '16'` for inputs `limit_rate 7.5, stop_loss_trigger 8, fresh_order_limit 10.95`; an older, now commented-out README example calls it with `product_type="optionplus"` and a stop-loss trigger **[FACT]** — it is the pricing calculator for ICICI's OptionPlus/cover-order product, which the API cannot even trade ("Margin and Option Plus orders cannot be placed… via the API", API docs **[FACT]**). **Decided:** affordability is computed from `get_funds()` (`allocated_fno`, `block_by_trade_fno`) / `get_margin("NFO")` plus our own arithmetic; the endpoint is called once in the trial and its answer recorded, nothing designed around it.

---

## 5. Consensus proposal

### 5.1 Verified constraints the design rests on

| Item | Value | Tag / source |
|---|---|---|
| Nifty lot | **65** (Oct–Dec 2026 contracts, NSE contract master 15 Oct 2026); semi-annual review — next possible change after the Oct monthly expiry | [FACT] stockmojo contract-master mirror; re-read daily from NSE_FO_contract file |
| Nifty option freeze quantity | **3,510 units = 54 lots** from 5 Oct 2026 (NSE/FAOP/76693, 1 Oct 2026); changed four times in 2026 | [FACT] NSE circular |
| Breeze order types | `limit`, `stoploss` (trigger in `stoploss`, limit in `price`); validity `day`, `ioc` (`vtc` in SDK); market orders rewritten by the SDK as LTP±10% (min 5 pts) limits | [FACT] API docs + SDK source |
| REST order statuses | Requested, Queued, Ordered, Partially Executed, Executed, Rejected, Expired, Partially Executed And Expired, Partially Executed And Cancelled, Freezed, Cancelled | [FACT] API docs; SDK `TUX_TO_USER_MAP` |
| Order notification | separate socket `livefeeds.icicidirect.com`; fields in §3 (Chen) | [FACT] SDK |
| Limits | 100 REST/min, 5,000/day; 10 orders/s combined | [FACT] brief §2.1 |
| Static IP | mandatory for API orders; change once/week | [FACT] ICICI FAQ |
| SEBI/NSE retail algo | 10 OPS threshold; below it no registration; tagging by broker; 5-year audit at broker | [FACT] NSE/INVG/67858 |
| Intraday auto-square-off | applies to FuturePlus/OptionPlus (time shown daily on ICICI's site); the API can only trade the regular `options` product, which has **no** intraday square-off — a long option not sold carries overnight, or on expiry day settles at 15:30 (ITM exercised in cash, OTM lapses) | [FACT] API docs + ICICI FAQ; [HYPOTHESIS] that ICICI never force-closes regular long options intraday — ask ICICI |
| Charges (Oct 2026) | STT **0.15%** of premium on sell (and 0.15% of intrinsic on exercise) since 1 Apr 2026; NSE transaction 0.03553% of premium both sides; SEBI ₹10/crore; stamp 0.003% buy; IPFT negligible; GST 18% on brokerage+transaction+SEBI; brokerage per order per the owner's plan (iValue reference: ₹20/order) | [FACT] Zerodha/Angel charge pages, ICICI iValue page; brokerage **parameter B** |
| Sandbox | none. `uat-breeze-connect` on PyPI is ICICI's own pre-release channel, not a customer sandbox | [FACT] PyPI |

### 5.2 A trade's life, trigger to flat

```
TRIGGER (from G1/G2/G3 fused card; G4 gives contract, stop plan, take-zone)
  │ pre-trade checks (<1 ms, all local):  state == ARMED & FLAT · 09:15:05 ≤ t ≤ 15:15 · not HALTED
  │   · capital ≥ 1 lot at max ladder price · qty ≤ freeze · book_stale == false · L1 age < 500 ms
  │   · session heartbeat < 90 s old · order socket alive · no live order of ours exists
  ▼
ENTRY LADDER (IOC, one REST call per rung; sized on the rung price)
  rung 0: ask + b0          TTL = until terminal notification, max 1.0 s
  rung 1: ask' + b1         (re-read L1)                       max 1.5 s
  rung 2: ask'' + b2        = G3.do_not_chase_beyond              max 1.5 s
  stop chasing when: price > trigger_ask + chase_cap, or t > 4 s, or G3.cancel_advice, or filled
  partial fills are kept; the position is whatever filled
  ▼
PROTECT (within 1 s of the first fill notification)
  place SL-limit SELL: qty = filled, trigger = entry − S (G4), limit = trigger − cushion
  cushion = max(5 pts, 4% of premium); 0DTE after 13:00: max(8, 6%)
  if the entry gets more fills: modify the SL quantity (never a second SL)
  ▼
MANAGE (software, every tick; the exchange SL is the disaster floor)
  ratchet the SL (modify) only in steps ≥ 2 pts and ≤ 1 modify / 10 s
  exit events from G4/G2 (THESIS-VOID, trail, take-zone, WINDFALL, EXPIRY-FLAT, STALL+driver-gone)
  ▼
ACTIVE EXIT (one object: the resting SL becomes the exit order)
  modify SL → limit SELL at bid − e0            TTL 1.0 s
  modify → bid' − e1                            TTL 1.5 s
  modify → max(lowerCktLm, bid'' − e2)          TTL 2.0 s     (band edge ≈ "market")
  still open after 5 s → ALARM (audio + banner), keep working at band edge, manual checklist
  if a notification says the SL already executed/partially → that is the exit; reconcile
  ▼
FLAT: realised net P&L = (avg_exit − avg_entry) × qty − charges_est;  capital += that
      audit rows written; G4/G1/G2/G3 receive the fill report; state → ARMED & FLAT
```

Buffers b0/b1/b2 and e0/e1/e2 are configuration with these defaults [HYPOTHESIS, calibrate in §6]: for premium < 150: b = 0.30 / 1.00 / 2.00, e = 0.30 / 1.00 / 2.50; for premium ≥ 150: b = 0.50 / 1.50 / 3.00, e = 0.50 / 1.50 / 3.50. G3's `urgency`: `rest` → a resting limit at ask − 1 tick with TTL 3 s then rung 0; `take` → rung 0; `take_now` → start at rung 1. Prices are rounded to the 0.05 tick and clamped inside `[lowerCktLm, upperCktLm]` from the live tick (no REST call).

### 5.3 A day's life

- **08:30–09:10 Preflight** (runbook §5.13): session, funds allocated to F&O == capital, contract master (lot, freeze, expiry), static IP check, both sockets up, clock sync, kill-switch dry run, yesterday's positions/orders = none (else adopt, §5.8), LIVE/PAPER banner.
- **09:14 Arm.** Pre-open connection warm: persistent HTTPS session to `api.icicidirect.com` kept alive. 09:15:00–09:15:05 no entries (band and book settle).
- **09:16 Notification probe** (one per day): place a 1-lot BUY limit at ₹0.05 on a far-OTM strike whose ask ≥ ₹1 (cannot fill), wait for `Ordered` on the order socket, cancel, wait for `Cancelled`. Proves the order socket, the auth, the IP registration and the round-trip latency before the first real trigger. Cost: 2 REST calls; ₹0 if unexecuted.
- **09:15–15:15 Trading** as §5.2; capital compounds on each realised exit.
- **15:15 No new entries** (parameter). **15:20 Flatten window:** any open position is exited by the active-exit ladder; must be flat by 15:25; 15:27 → band edge and alarm. Non-expiry-day fallback if truly unfilled: the long carries overnight (loss bounded by premium already paid); expiry-day fallback: cash settlement at 15:30.
- **15:30 Close:** reconcile `get_trade_list` against our fills, `get_portfolio_positions` must be empty, archive, `ws_disconnect()`, write the day note. Capital variable resets to ₹1,00,000 at the next start **[OWNER]**; the broker allocation is topped up or trimmed to ₹1,00,000 + charges buffer in the morning.

### 5.4 Order state machine (ours, layered on Breeze statuses)

```
NEW ──send──▶ SENT ──ack(order_id)──▶ ACKED ──notif Ordered/Queued──▶ OPEN
 │                │                      │                               ├─ Partially Executed ─▶ PARTIAL ─▶ (Executed | Partially Executed And Cancelled/Expired)
 │                │ timeout 2 s          │                               ├─ Executed ──────────▶ FILLED
 │                ▼                      │                               ├─ Cancelled / Expired ▶ DEAD
 │             UNKNOWN ──query by user_remark in get_order_list──▶ adopt or declare LOST
 │                                                                       └─ Rejected / Freezed ─▶ REJECTED (reason logged; Freezed ⇒ re-slice)
 └─ rejected locally by pre-trade checks ──▶ BLOCKED (reason to the owner)
```
Rules: one live order of ours at a time, per side, ever. A notification for an unknown `orderReference` on our contract and side is *adopted* (the ack may arrive after the notification at 09:15). Terminal status from either source (socket or REST) closes the state; conflicting sources → REST `get_order_detail` is the tie-breaker.

### 5.5 Sizing exactly as the owner specified

```
lot            = 65 (contract master, daily)
p_max          = rung-2 price = ask + b2                      # the most we could pay
reserve        = charges_est(p_max, lots_guess) + 0.5% × capital   # chase + charge buffer
lots           = floor((capital − reserve) / (p_max × lot))
lots           = min(lots, freeze_lots = 54, sanity_cap)      # sanity_cap = 2 × floor(capital/(ask×lot))
if lots < 1: BLOCKED("premium too rich for capital")
qty            = lots × lot ; if qty > 3,510 → slices of ≤ 3,510 sent back-to-back (≤ 3 orders/s)
```
- **Margin reality [FACT]:** a long option blocks the premium only (`block_by_trade_fno` rises by price × qty); no SPAN. The broker funds check is the physical ceiling: allocate exactly the day's capital (+₹1,500 charges buffer) via `set_funds` each morning, so an oversized or duplicate buy is rejected by ICICI itself.
- **Indivisible remainder:** at P=120, 12 lots use ₹93,600; ₹6,400 idles. That idle cash is the rounding of the owner's rule, not a reserve; it is shown on screen as "idle".
- **Capital tracking:** `capital = start + Σ realised net P&L of the day`; unrealised never counts (one position at a time, so sizing only happens flat). Net = gross − estimated charges (formula §5.10); the morning reconciliation replaces estimates with the contract note. Capital resets to ₹1,00,000 each morning **[OWNER]**.
- **Compounding up requires that sale proceeds are reusable intraday at ICICI** — **[HYPOTHESIS]**, verified on the one-lot trial day by selling, then checking `get_funds().allocated_fno`/`block_by_trade_fno` before buying again. If proceeds are not released until T+1, "use the profits" degrades to all-in on the remaining allocation and the owner must know (§9).
- Freeze slicing is implemented but unreachable at ₹1 lakh: exceeding 54 lots needs ≈ ₹2.86 lakh at P=80 or ₹1.43 lakh at P=40 (the old ₹40 floor). It is exercised only in paper mode.

### 5.6 Entry and stop pricing: why these numbers

- Breeze's own "aggressive limit" is LTP +10% (≥ 5 pts) **[FACT]** — far wider than needed; our rungs stay inside ask + 2–3 pts, which the owner's "don't chase" instinct and G3's `do_not_chase_beyond` both say.
- IOC removes every cancel from the entry path and makes "a forgotten resting buy" impossible. NSE and Breeze both document IOC **[FACT: docs]**; its acceptance on NFO options via Breeze is confirmed in the trial **[HYPOTHESIS until then]**.
- The stop cushion (5 pts / 4%) is below the trigger so the triggered limit is still marketable after one or two fast prints; a sell that still rests after a 5-point gap is the unfilled-stop failure, handled by the active exit while alive and by the manual checklist when dead.
- Expected order-path latency budget **[HYPOTHESIS, measured daily by the probe]**: trigger → request on the wire < 2 ms (codes pre-resolved, session warm) → broker ack p50 ≤ 300 ms, p95 ≤ 800 ms → fill notification ≤ 500 ms after. Alarm if ack > 2 s. Ladder TTLs above assume this; they scale with the measured p95.

### 5.7 Reconciliation and position truth

- **Primary:** the order-notification socket (zero REST). **Fallback:** after any order action with no notification in 2 s → `get_order_detail` (1 call); every 5 min while in a position → `get_portfolio_positions` (≈ 75/day); on each exit → `get_trade_list` (1 call); heartbeat `get_funds` every 120 s (≈ 190/day). Executor total ≈ 450 calls/day against the ≈ 1,500 G5 leaves — see §5.14.
- **Two books:** *intent book* (ours: what we decided, which order ids we own) and *broker book* (positions + today's order list). **The broker book is truth for quantity; ours is truth for intent.** Disagreement handling: broker shows a quantity we do not hold → ALARM, place a protective SL on it immediately, then flatten it (an unintended position is never kept); we hold but the broker shows zero → mark closed from `get_trade_list`, audit; a live sell order we do not own on our contract → cancel it (it could make us short).
- Reconciliation runs at start, after every terminal order state, every 5 minutes in position, and at 15:30.

### 5.8 The dead-session problem

A dead session cannot sell. Five layers:

1. **Exchange-side SL-limit from the first fill** (D3). Its trigger/limit are also written to the audit log so a restart or the owner's app can find them.
2. **Heartbeat:** `get_funds` every 120 s; a response without `Status == 200` or with an error string, or an order-socket disconnect, or a `subscribe_feeds` error string (brief §2.1) → **SESSION-DEAD alarm**: continuous audio, red full-width banner, the manual checklist opened on screen. No silent retries while a position is open.
3. **Manual-exit checklist (ICICI app/web):** (a) Orders → find the resting SL sell for the contract; (b) **modify** it to a limit sell at bid − 1 — or, if the app will not change the type, **cancel it first, confirm the cancel, then** sell the position (never sell with the SL still alive: a double exit is a naked short); (c) confirm Positions shows 0; (d) press "I exited manually" on the dashboard so the executor re-reconciles instead of re-protecting.
4. **Re-login:** the owner gets a fresh `apisession` from the Breeze login page and pastes it; the EXECUTOR hot-swaps the session (`generate_session` again, reconnect the order socket) without restarting FEED. Whether the old token is invalidated by a new login is **[HYPOTHESIS]** (trial).
5. **Restart with an open position:** start → `get_portfolio_positions` + today's `get_order_list` → rebuild the book → if a position exists with no resting SL → place one now (trigger from the audit log, else entry − S from the trade record, else LTP − 10) → cancel any unknown order → only then accept triggers. The state is displayed before arming; the owner confirms with one key.

### 5.9 Account-level safety rails (compatible with all-in)

| Rail | Default | Owner-switchable | Mechanism |
|---|---|---|---|
| Daily hard stop | day ends when capital ≤ (1 − X) × start, **X = 20%** proposed | yes (X or off) | HALTED state; flatten if in position; no entries until tomorrow |
| Consecutive-stop pause | 3 consecutive stop-outs → 30 min no entries | yes | counter in the book; resets on a win |
| Kill switch | dashboard hotkey + a `KILL` file in the run directory + a physical USB key optional | no | cancel all our orders → active-exit ladder at band edge → HALTED; needs an explicit flag to re-arm |
| Broker-side ceiling | F&O allocation = capital + ₹1,500 | no | ICICI rejects what the allocation cannot pay |
| No-naked-short invariant | live sell qty ≤ held qty, always; a sell with no long is BLOCKED | no | pre-trade check + notification cross-check |
| Order-rate limiter | ≤ 3 order requests/s; ≤ 400 order calls/day; ≤ 90 REST/min from the executor | no | token bucket; excess → BLOCKED with alarm |
| Time rails | entries 09:15:05–15:15; flatten from 15:20; nothing after 15:28 | yes (times) | clock from NTP; refuse to arm if drift > 1 s |
| Stale-book rail | no entry if G3 `book_stale` or L1 age > 500 ms; in position with the held contract silent > 15 s → treat as MANAGE-by-SL only and alarm | yes | from G3/G5 flags |

### 5.10 Charges and net P&L

Per round trip of q units bought at P_in and sold at P_out, with n_in/n_out orders and brokerage B per order:

```
brokerage = B × (n_in + n_out)
nse_txn   = 0.0003553 × (P_in + P_out) × q
sebi      = 0.000001 × (P_in + P_out) × q
stt       = 0.0015 × P_out × q
stamp     = 0.00003 × P_in × q
gst       = 0.18 × (brokerage + nse_txn + sebi)
charges   = sum of the above ;   breakeven points = charges / q
```
Example at P=120, 12 lots (780 units), flat exit, B=₹20: brokerage 40.00, NSE 66.51, SEBI 0.19, STT 140.40, stamp 2.81, GST 19.21 → **₹269 = 0.35 pts**. STT is half the bill and scales with premium; brokerage matters only at 1–5 lots.

**Breakeven in premium points per trade (B = ₹20/order, one order each side):**

| Premium \ lots | 1 | 5 | 10 | 13 | 20 | 54 |
|---|---|---|---|---|---|---|
| 60 | 0.87 | 0.29 | 0.21 | 0.20 | 0.18 | 0.16 |
| 80 | 0.92 | 0.33 | 0.26 | 0.25 | 0.23 | 0.20 |
| 120 | 1.01 | 0.43 | 0.36 | 0.34 | 0.32 | 0.30 |
| 160 | 1.11 | 0.52 | 0.45 | 0.44 | 0.42 | 0.39 |
| 200 | 1.20 | 0.62 | 0.55 | 0.53 | 0.51 | 0.49 |
| 300 | 1.44 | 0.86 | 0.78 | 0.77 | 0.75 | 0.72 |

Add the spread crossed twice (0.05–0.5 pts on ATM weeklies, more on ITM/expiry) for the true round-trip cost: ≈ 0.5–1.0 pts at ₹1 lakh. The 16 Oct paper day (12 trades, honest fills, gross −₹25,610) would have paid ≈ ₹2,900 in charges: **net −₹28,500, −28.5%** **[FACT: CSV + formula]**. Exercise instead of sale on expiry day costs the same STT rate on intrinsic value since April 2026 — no longer a trap, but the fill price is the settlement price, not a price you chose.

### 5.11 The risk arithmetic, plainly (information, not a sizing recommendation)

**Lot 65, start ₹1,00,000, all-in `lots = floor(capital/(P×65))`, charges included, stop fills exactly at the trigger.**

| Premium P | Lots (cost) | Stop −8 | Stop −10 | Stop −15 |
|---|---|---|---|---|
| 80 | 19 (₹98,800) | −₹10,142 (10.1%) | −₹12,608 (12.6%) | −₹18,771 (18.8%) |
| 120 | 12 (₹93,600) | −₹6,497 (6.5%) | −₹8,054 (8.1%) | −₹11,947 (11.9%) |
| 200 | 7 (₹91,000) | −₹3,896 (3.9%) | −₹4,804 (4.8%) | −₹7,075 (7.1%) |

**Gap-through — trigger −10, fill 20 points lower (−30):** P=80: **−₹37,260 (37.3%)**; P=120: −₹23,624 (23.6%); P=200: −₹13,887 (13.9%). One such print at P=80 is more than a third of the day's capital in one trade.

**Consecutive −10 stops, re-sized all-in each time (premium held at P):**

| P | after 3 | after 4 | after 5 | capital after 5 |
|---|---|---|---|---|
| 80 | −32.5% | −40.5% | −47.8% | ₹52,166 |
| 120 | −22.2% | −28.2% | −34.3% | ₹65,735 |
| 200 | −13.7% | −17.9% | −22.0% | ₹78,018 |

**Probability of at least one run of 4 consecutive losses somewhere in a 12-trade day** (independent trades): win 41% (MYTHOS measured): **48.0%** (≥3: 75.8%; ≥5: 27.2%); win 50%: 29.9%; win 55%: **21.5%** (≥3: 47.8%; ≥5: 8.9%); win 60%: 14.5%. In an 8-trade day at 41%: 32.0%; at 55%: 13.1%. Read: at MYTHOS's win rate, a 4-stop streak (−28% at P=120, −40% at P=80) is a coin-flip event *every day*.

**Compounding upside:** three consecutive +12 wins at P=120, all-in each time: 12 → 13 → 15 lots, ₹1,00,000 → ₹1,09,073 → ₹1,18,906 → **₹1,30,259 (+30.3%)**. Three +6 wins: +13.9%. The rule rewards a real edge as hard as it punishes a streak.

**Expectancy at MYTHOS's own stats** (41%, +4.3/−4.7, 12 lots at P=120): **−₹1,055 per trade** after charges (charges ≈ ₹268 of it) → ≈ −₹12,700 per 12-trade day. The 16 Oct day (−28.5% net) is that distribution, not bad luck.

**Kelly, for reference:** negative at the measured stats (no stake is right); 17.5% at 55%/+12/−10 — all-in at P=120 with a −10 stop risks ≈ 8% per trade, i.e. about half-Kelly *if that edge is real and stops fill*. Amara's one-line conclusion: **the sizing rule is survivable only with an edge that has not yet been measured; the day-stop (X) is the only thing that bounds a bad day, and the gap-through is the only thing a stop cannot bound.**

### 5.12 Audit log

SQLite (WAL, dedicated writer thread, the pattern from MYTHOS), append-only, one file per month, never deleted: `decisions` (ts, trigger id, inputs hash, contract, lots, why, verdict BLOCKED/SENT), `orders` (client id = `user_remark`, broker id, every status transition with ts and source socket/REST), `fills` (per notification, raw JSON verbatim), `positions` (every reconciliation: ours vs broker), `capital` (every change), `alarms`, `operator_actions` (kill, manual-exit acknowledgement, re-login), `latency` (per order: wire, ack, first notification). A daily `trades_YYYY-MM-DD.csv` with **net** P&L as before. Every row carries both wall-clock and monotonic timestamps; the 15:30 reconciliation also stores the broker's trade list.

### 5.13 Operator runbook

**Morning (08:30–09:14).** Login → paste `apisession` → preflight GO/NO-GO: session (`get_customer_details`), funds (`get_funds`: `allocated_fno` == capital + buffer, else `set_funds`), positions/orders = none (else §5.8 step 5), contract master (lot, freeze, expiry string), public IP == registered static IP, NTP drift < 1 s, price socket + order socket connected, disk free, audio test, kill-switch dry run (PAPER), the LIVE/PAPER banner read aloud. Any NO → do not arm.
**Intra-day.** Watch the status strip: heartbeat age, order-socket age, "books agree", capital, day P&L vs X, live order rung/TTL. On an alarm follow the on-screen checklist; never place manual orders while ARMED (kill first). Do not touch the ICICI app's order book while a system order is live.
**Close.** 15:20 flatten window → 15:30 reconciliation → positions empty → archive → `ws_disconnect()` → day note (what the executor did wrong, if anything). Next morning: contract note vs estimated charges.

### 5.14 Budget and latency

REST per day (executor only): probe 2 + per trade ≈ 12 (entry 1–3, SL 1, ratchets ≤ 6, exit 1–3, post-trade 2) × 12 trades ≈ 150 + heartbeat 190 + position checks 75 + reconciliations 10 ≈ **≈ 430**, inside the ≈ 1,500 G5 leaves; peak rate during a trade ≈ 6 calls in 10 s, far below 100/min and 10 orders/s. Latency: one HTTP call per action, persistent TLS session, pre-resolved contract strings (expiry built from an explicit English month list — brief §2.1), no SDK `import` in the hot process (it downloads the scrip master).

---

## 6. Validation plan

**6.1 Paper-through-real-path.** One executor code path; a `LIVE` flag selects the transport: Breeze (live) or a `FillSimulator` (paper) that consumes the same L1/L5 tick stream and returns the same notification messages (same field names, same statuses, same timing). The simulator fills a buy limit at P ≥ ask immediately for `min(qty, visible ask qty up to P)` walking the ladder from G3's `ask_ladder`; a limit below the ask fills only when prints at ≤ P have consumed the quantity that was ahead at placement (queue model, conservative); IOC remainders expire; it injects measured latency (ack and notification from the daily probe distribution), 1% random rejections, band and freeze checks, and the sell side symmetric on bids. Honest marks: buy at ask, sell at bid. The paper book is reconciled against a simulated broker book exactly as live, so the reconciliation code is exercised daily.

**6.2 Acceptance tests before the first live lot (all in paper, all automated):** every state transition in §5.4 reached by injected notifications including out-of-order (notification before ack), duplicate and conflicting messages; timeout → UNKNOWN → adopt/LOST both branches; a partial entry followed by SL quantity modify; freeze slicing at 55+ lots; band clamping; kill switch from every state; restart with an open position (three sub-cases of §5.8 step 5); the no-naked-short check blocking a sell that exceeds the long; the day-stop and pause counters; the rate limiter; clock-drift refusal. Twenty sessions of paper-through-real-path with zero unresolved reconciliation mismatches and zero invariant violations.

**6.3 One-lot live trial day (owner-clicked, not signal-driven).** On a liquid ATM weekly, 3 DTE: (1) 09:16 probe; (2) BUY 1 lot IOC at ask + 0.30, record ack/notification latency; (3) SL-limit sell placed — confirm acceptance, confirm no short-option margin block (`get_margin`), confirm it shows in the app; (4) modify the SL trigger up by 2 pts; (5) active exit by modify-to-limit; (6) check funds: are sale proceeds immediately reusable? (7) BUY again, then test cancel-then-IOC exit; (8) BUY again, then operator kills the session (log in elsewhere) → does the alarm fire within 2 min, does the resting SL survive at NSE, exit manually per checklist, press "exited manually", re-login hot-swap; (9) GTT single-leg placed and cancelled, its order-book entry recorded; (10) `limit_calculator` called once, answer recorded; (11) deliberately send a 2-lot sell against a 1-lot long in PAPER to prove the block, never live. Budget: ≈ ₹1,000 of charges and slippage. Each step has a pass criterion written before the day.

**6.4 Pre-registered bar before all-in sizing is enabled (execution quality only — the strategy's edge bar belongs to G7):** across ≥ 5 live sessions at 1 lot driven by real signals: median |simulated fill − real fill| ≤ 0.3 pt and p95 ≤ 1.0 pt (else the paper results are untrustworthy and the ramp stops); every fill protected by an SL within 1 s (p95); zero duplicate orders, zero naked-short attempts, zero unresolved mismatches; ack p95 ≤ 1 s. Then ramp 1 lot → 25% of all-in → 50% → all-in, ≥ 3 sessions each with no execution incident. The owner may shorten the ramp (it is his capital); the incident counters are objective and displayed.

---

## 7. Risks and failure modes (nothing to do with the signal)

1. **Unfilled stop on a gap** — the SL-limit triggers but its limit sits above every bid. Cushion; active exit to band edge; alarm; manual. Residual: a circuit or an empty book (expiry afternoon), bounded only by the premium.
2. **Duplicate buy** after a timeout or retry bug. UNKNOWN is queried, never re-sent blindly; `user_remark` ids; the broker allocation rejects a second buy at 94% utilisation; the sanity cap.
3. **Double exit → naked short** (resting SL plus a manual or software sell). One-sell-order invariant, modify-not-replace, the checklist's order of operations, a notification cross-check that cancels any second sell.
4. **Dead session with a position** (§5.8). Residual: the SL fires at a bad price and nobody ratchets it.
5. **Static IP mismatch** — every order "Request Denied" while data flows normally. The 09:16 probe; the morning IP check.
6. **"Freezed" rejection** at compounded sizes. Slicer; daily freeze value from the contract file.
7. **Band rejection** at the open or on a circuit. Clamp to `lowerCktLm/upperCktLm` from the tick; alarm when the clamp binds.
8. **EOD left open.** No broker auto-square-off exists for this product; an unfilled 15:25 exit carries overnight or settles on expiry. Flatten ladder, alarm, checklist.
9. **Stale L1 pricing** at 09:15 or in a tick storm. L1 age gate; IOC (a miss costs nothing).
10. **Hidden SDK calls** doubling latency and budget. Own REST client; budget counter on screen.
11. **Partial entry, full-size stop** (or the reverse). SL quantity always equals held quantity; modify on every fill.
12. **Funds not recycled intraday** — the second trade rejected after a winning first. Verified on the trial; sizing reads live `get_funds` when it disagrees with the ledger.
13. **Lot or freeze changes** (freeze revised four times in 2026; lot review due around end-October). Never hard-code; contract file daily; refuse to arm on a stale file.
14. **Order socket silently dead** while the price socket lives. 2-second REST fallback after each action; the probe; socket age on screen.

---

## 8. Interfaces

**From G3 (force & flow):** the trigger packet as G3 defined it — `urgency ∈ {rest, take, take_now}`, `ask_now`, `ask_ladder`, `expected_walk`, `spread_now`, `recommended_limit`, `do_not_chase_beyond`, `book_stale`, `cancel_advice`. We map `rest`/`take`/`take_now` to the ladder's start rung and use `expected_walk` to size against the visible ask. **To G3:** our fill report (rungs used, fill price vs `ask_now`, walk observed, time to fill) so the buffer hypotheses get calibrated.

**From G4 (contract & exit geometry):** instrument, suggested lots, reference ask, stop plan (spot level, premium trigger, cushion advice for 0DTE), take-zone, exit events with reason strings. We size (owner's rule) and may reduce lots only by funds/freeze/sanity caps — never by a risk cap unless the owner sets one (`risk_cap_frac`, default off). **To G4:** fills, working-order state, realised net P&L, the "absorbable quantity within 2 pts" measure per hero contract from L5 depth (for strike choice), and the owner's X and pause decisions.

**From G5 (data platform):** the order path shares the pre-warmed session but owns its own HTTPS connection; the order-notification socket runs in the EXECUTOR process and publishes fills on ZMQ; L1/L5 rows and circuit limits from shared memory with age; `feed_stale` flags; the daily contract file (lot, freeze, expiry). **To G5:** our REST call counts per minute (one shared budget), latency stamps per order, the probe's timings.

**From G1/G2:** triggers and exit hints (`destination.reached`, `wind.reset`) routed through G4's card; we never act on them directly.

**To G7 (red team):** every invariant in §2 as a testable property, the fill-model error series, the incident counters.

---

## 9. Open questions for the owner

1. Static IP: does your API key have a declared static IP, and is your home line static? If not, ISP static IP or cloud executor (we recommend ISP).
2. Day-stop X (we propose 20%) and the 3-stop / 30-minute pause: accept, change, or switch off?
3. Brokerage plan (B per order) and whether ICICI charges per order or per executed order; confirm F&O API order permission is enabled on the account.
4. Are option sale proceeds reusable intraday in your account (needed for "use the profits")? We will test; your knowledge from manual trading helps.
5. The flatten times (15:15 last entry, 15:20 flatten, 15:25 flat) — acceptable?
6. May we run the 09:16 notification probe (a 1-lot ₹0.05 order that cannot fill) every day?

---

## 10. One-paragraph summary for the master design

The executor is a one-position, one-live-order-per-side state machine: a fused trigger becomes a position through IOC limit orders laddered from ask+0.3 to ask+2 (never resting on momentum, never chasing past G3's cap); every fill is protected within a second by an exchange-held stop-loss-limit order (trigger entry−S, limit 5 points lower) that survives a dead session; the trade is managed in software and exited by modifying that same resting order into an aggressive limit, escalating to the band edge, with alarms and a manual checklist when it cannot. Sizing is the owner's rule exactly — `lots = floor((capital − reserve)/(p_max × 65))`, compounding on realised net P&L, reset to ₹1,00,000 daily — made physical by allocating exactly that capital to the F&O segment so ICICI's own funds check rejects duplicates and oversizing. Rails compatible with all-in: a proposed 20% day-stop and 3-stop pause (owner-switchable), a kill switch, a no-naked-short invariant, rate and time limiters, and reconciliation with the broker as truth for quantity. The arithmetic the owner must see: a −10 stop costs 5–13% of capital by premium, a 20-point gap-through 14–37%, a 4-stop streak 18–40% — and at MYTHOS's measured 41% win rate that streak occurs on about half of all 12-trade days; a 3-win day of +12 compounds to +30%. Verified underneath: lot 65, freeze 3,510 (54 lots), STT 0.15% on sale since April 2026, static IP mandatory, 10 orders/second is the registration threshold, no sandbox exists, and the API cannot use the broker's auto-squared-off intraday products — flattening before 15:30 is entirely ours.

---

*Sources (verified 17 Oct 2026):* Breeze API docs (api.icicidirect.com/breezeapi/documents) · breeze-connect 1.0.69 source (PyPI) and README (github.com/Idirect-Tech/Breeze-Python-SDK) · ICICI Direct FAQs on static IP, OPS and brokerage; iValue plan page · NSE circular NSE/FAOP/76693 (1 Oct 2026) · stockmojo.in contract-master mirror (15 Oct 2026) · NSE/INVG/67858 (5 May 2025) and SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 · Zerodha and Angel One charge pages (STT from 1 Apr 2026) · Business Standard, 27 Sep 2021 (SL-M discontinued for options) · MYTHOS `trader.py`, `config.py`, `KILL_CRITERION.md`, `archive/trades_2026-10-16.csv`.
