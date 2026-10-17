# APEXOPTIONS — OPEN QUESTIONS FOR THE OWNER

*Consolidated from the brief and all seven working groups, de-duplicated and ranked by how much of the build each answer unblocks. The owner said he will answer when necessary; every item states the assumption the team is building on in the meantime. Chief architect, 17 Oct 2026.*

*Revised after the red team (G7): OQ-0, OQ-22 and OQ-23 added; OQ-9 promoted to Tier A and re-dated; OQ-4 demoted (the new trust design makes it non-blocking); OQ-12 demoted (assumed); OQ-11 answered by the team — rejection sails are out of v1.*

## Tier A — decides whether day one places an order at all

| # | Question | Why it matters | Assumption until answered |
|---|---|---|---|
| OQ-0 | **The kill rule.** Will you pre-commit that if the shadow sequential test crosses its KILL line, the trigger is retired — not retuned on the same days — and that any retune is tested only on sessions recorded after it? | The only protection against "six full rebuilds, each shipped live unproven". Without it no validation means anything. | Asked before the first shadow trade. |
| OQ-9 | **Monday 19 Oct.** May the probe record Monday's expiry session (record only, no orders)? Will MYTHOS run that day on the same API key — making the probe a second socket — or will you pause it? | The first live measurement; four facts every engine depends on. Expiry-day data is exactly what the 0DTE rules need. | Yes; MYTHOS paused, or the probe treated as a second socket. |
| OQ-22 | **Presence.** On live trading days, will you be at the screen the whole session? | A dead session with an open position needs a human with the broker app; if you are away, the trading window shrinks to the hours you are present. | Present all session. |
| OQ-23 | **Stop-loss margin.** Can you ask ICICI whether a pending SL-limit sell against a long option is margined as a square-off or as a fresh short? | If margined as a short, at 94% utilisation the protective stop is rejected and the position is unprotected against a dead session (go/no-go, D-045). | Tested in the one-lot trial. |
| OQ-1 | **Static IP.** Does your Breeze API key have a declared static IP, and is your home line static? If not: an ISP static-IP add-on, or a cloud executor? | ICICI: "A primary static IP is mandatory"; the rejection is *"Request Denied: The IP address used does not match with the static IP declared…"*. Data will flow and no order will go. | ISP static IP; executor stays local (cloud hop = 20–60 ms each way and a second failure domain). |
| OQ-2 | **Account-level rails.** Day-stop X (team default −20% of start capital) and the 3-consecutive-stop / 30-minute pause: accept, change, or switch off? Any per-trade risk cap (G4 assumed 6–8% of capital, which under all-in sizing is really a strike-eligibility rule)? | At MYTHOS's 41% win rate, a 4-loss run (−28% at ₹120 premium, −40% at ₹80) happens on ~48% of 12-trade days. Only X bounds a bad day; only strike choice bounds a bad trade. | Defaults on, logged as the owner's decision when changed. |
| OQ-3 | **Are option sale proceeds reusable intraday in your ICICI account?** | "Use the profits and go all in again" is impossible if proceeds release T+1; the rule then degrades to all-in on the remaining allocation. | Tested on the one-lot trial day; your manual-trading experience would settle it sooner. |
| OQ-4 *(demoted to Tier B by the red team)* | **16 Oct certificate.** How did you "save" the certificate — browser viewer, `certmgr`? Please check `certmgr.msc → Intermediate Certification Authorities` for **GlobalSign GCC R46 EV TLS CA 2025** and its date, and run `openssl s_client -connect livestream.icicidirect.com:443 -servername livestream.icicidirect.com -showcerts` — one certificate served or two? | The saved `cert.pem` is UTF-16, leaf-only and referenced by nothing — it could not have fixed anything. If Windows cached the missing intermediate when you viewed it, the next re-issue (≈ April 2027) will repeat 16 Oct unless the new system trusts via the Windows store with AIA. | `truststore` + pinned bundle + 5-s diagnostic probe. |
| OQ-5 | **Exit geometry.** Do you accept stops/targets expressed internally in spot points and % of capital (premium points shown on the card) instead of a fixed −10/+12? Is +12 still the target, or should the destination (next wall) set it with +12 as the floor? Hold to the destination when a leg takes 10–40 minutes, or target only the first ~100 pts of a void? | Decides G4's exit plan, G2's pays arithmetic and G6's stop placement. Your hand habit (5–7 min) and the sail metaphor (hold to the destination) pull opposite ways. | Structural stop capped in % capital; take-zone from the projection; +12 as a floor; trail on the futures path from +1R; hold to destination or wind-reset. |

## Tier B — shapes the design, answer before the first shadow week

| # | Question | Why it matters | Assumption |
|---|---|---|---|
| OQ-6 | **Which domino have you actually watched?** The usual first mover(s) and the timescale (seconds or minutes). | Decides whether Study F1 is looking for the right events. G1's reading: banks lead on bank-catalyst days; futures lead on index days. | Bank-group-led episodes on catalyst days, tens of seconds. |
| OQ-7 | **Domino instrument preference**: convex ATM (bigger % move, exposed to IV sign and theta) or Δ 0.6–0.85 ITM (tracks the move, wider spread, more capital per lot)? | F3 and the selector's score are optimised for your answer. G4 refutes Δ≈1 for 5-minute holds. | DTE-dependent delta bands (D-021). |
| OQ-8 | **Expiry day after 13:00**: prefer next week's contract (one-fifth the rupees, one-fifth the risk), or 0DTE ITM Δ ≥ 0.8 — or both on the card with you choosing? | 0DTE ATM all-in risks 1.3–1.9% of capital per adverse spot point. **This week's expiry is Monday 19 Oct** (Tuesday is Dussehra). | Next week preferred; 0DTE only at Δ ≥ 0.8 within the cap; none after 14:45. |
| OQ-9b | **Measurement first, continued.** Accept that the first ≥ 10 sessions are pure recording (no thresholds tuned before session 5), and may probe 2 on Wed 21 Oct open a second socket on the live session (a refusal could drop the running socket)? | See OQ-9. | Yes. |
| OQ-10 | **Vetoes.** Should the Greeks' LATE/PRICED verdict or G3's FAKE ever block a real order, or only colour the card until each has cleared its pre-registered bar? | Every veto is a way to be late again; every missing veto is a way to buy the IV spike. | Advisory until the bar is met; then veto rights for LATE/PRICED only. |
| OQ-11 *(answered by the team: out of v1, D-034)* | **Rejection sails** (bounce off a wall G3 says is holding) — wanted, given MYTHOS's bounces were its losers? | Doubles the trigger surface. | Yes, but only with G3 HOLD-STRONG and the same wind detector. |
| OQ-12 | **The recorded MYTHOS frames** (30+ sessions) may be used for all validation studies? | They are the only history; low-resolution, no depth. | Yes. |
| OQ-13 | **Full constituent lists** for the three indices (NSE CSVs: `ind_nifty50list.csv`, `ind_niftybanklist.csv`, `ind_niftyfinancelist.csv`) and whether BankNifty futures subscribe under `CNXBAN` on NFO on your account. | The factsheets list only the top 10 per index. | Downloaded from NSE on the first build day; CNXBAN tried first. |

## Tier C — operational, answer when convenient

| # | Question | Assumption |
|---|---|---|
| OQ-14 | Brokerage plan (₹ per order; charged per order or per executed order); F&O API order permission enabled on the account? | ₹20/order; enabled. |
| OQ-15 | Flatten times: last entry 15:15, flatten from 15:20, flat by 15:25 — acceptable? | Yes. |
| OQ-16 | May the system place a daily 09:16 notification probe (a 1-lot ₹0.05 buy that cannot fill, cancelled at once) to prove the order socket, auth and IP before the first real trigger? | Yes (2 REST calls, ₹0). |
| OQ-17 | Browser (Chrome/Edge), monitor refresh rate, single or dual monitor; alarm channel = Windows toast + audio from the supervisor, browser secondary — acceptable? | Chrome, 60 Hz, yes. |
| OQ-18 | Tick-log retention (≈ 1–2.5 GB/day compressed)? Does ICICI's 5,000/day window reset at midnight IST or roll 24 h? | 90 days; midnight IST (the stricter reading is used). |
| OQ-19 | Which force-detector state changes deserve sound: WEAKENING, BREAK-IMMINENT, VACUUM, HOLD-STRONG, FAKE? Levels shown in spot points, futures points, or both? | First three; both, spot primary. |
| OQ-20 | Market-memory horizon: 10 trading days with 8%/day decay (20 days for levels held twice or more)? | As stated. |
| OQ-21 | Exact `breeze-connect` version installed (team verified behaviour against 1.0.69). | 1.0.69 or later. |
