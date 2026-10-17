# MyFnO and iCharts: what they offer and what ApexOptions could borrow

Research date: 2026-10-17. Goal: find ideas from two Indian options-analytics sites that would help a NIFTY weekly option **buyer** (CE/PE only) decide faster or better on ApexOptions, a local tick-by-tick dashboard.

---

## 0. How this was researched (and its limits)

| Source | Status |
|---|---|
| `myfno.com/#wall` (the app shell) | **Read directly** (WebFetch). It is a single-page JS app. Only the menu, toolbar labels and controls render without login. No data and no screen contents are visible. |
| `myfno.com/pricing` | Read directly. It now redirects to `myfno.app/pricing.html`, which was **read directly** (plans and limits below). |
| `myfno.app/` (the new app) | Read directly. The shell only (nav labels, filter builder). |
| `myfno.com/Launch`, `/Features`, `/Support`, `/Videos` | Read directly. `/Features` is the richest first-party description. |
| `help.myfno.com` (official helpdesk) | Read directly: the putcall, Option Chain, Matrix, MAXZONE, Markets and Heatmap articles, plus the Strategy category. Most were last updated in 2018–2022. |
| `blog.myfno.com` | Read directly. No feature posts were visible. |
| `icharts.in/opt/index.php` | **Read directly, but it is almost empty without JS or login.** Only the footer links render. |
| `icharts.in/opt/Tools_at_a_Glance.php` | **Read directly.** This is the full tool catalogue, names only. |
| `icharts.in/opt/Documentation.php` | Read directly. It documents Straddle/Strangle charts, the Futures chart, the Date field and indicator templates. |
| `icharts.in/opt/MultiStrikeOI.php`, `StraddleCharts.php` | Fetched. Both return a **login wall** (Tradejini co-branded). `Pricing.php` returned a fetch error. |
| Secondary sources (marked **[2nd]** below) | Strike.money reviews of both sites (written by a competitor, so biased); two Twitter threads mirrored on rattibha.com (2022) describing iCharts tools; iCharts' own YouTube video descriptions; a Tradejini blog on the CE-PE OI difference. |

Raw `curl` to both sites was blocked by the sandbox proxy (403), so I could not inspect HTML or JS bundles. No login was attempted. Where a layout detail is inferred rather than observed, it says "inferred".

---

## 1. MyFnO (myfno.com / myfno.app), by Seediff SoftSolutions, Mumbai, "since 2001"

### 1.1 Overall shape
- It is a 100% web app with three top tabs. Each tab is a menu of hash-routed screens (read from the live shell):
  - **markets:** wall, scans, adv/dec, heatmap, sectors, bubbles, turnover, fii, alerts
  - **stocks:** watch, dashboard, charts, trends, compare, rankings, periods, ranges, changes
  - **options:** putcall, chain, matrix, flow, profile, maxzone, volatility, strategy, wizard, spreads, screener, positions
- **Global metric tabs** apply across screens: Price, OI, Volume, IV, PCR, Basis, OHLC, VWAP, Spot, HV, IVP, limit, HiLo, Delivery, Rollover, RollCost, Rating, Sector, Tech_alerts, LongShort, AllOptions, MaxOI, maxpain, greeks, time, custom, charts, signals.
- **Display modes:** value / change / %chg. Trend measures: trend / %avg / %range / %tile (percentile).
- **Interval selector:** 5, 10, 15, 30 and 60 min, day, week, month, quarter, year. "% change over the last X minutes" works everywhere, which is the core idea. The helpdesk says this needs GOLD+ on the old plans.
- **Theme** (dark/light/color) and a **server selector** (main/alternate/backup).
- **Layout views:** table / cards / list / graph. Chart toggles include stacked, overlap, gradient, smoothen, logscale and sparkline. Export to XLS, CSV or image.
- **Interaction model:** this is what makes the site sticky.
  - **Hover** on any symbol or strike opens a quick-info tooltip (price, sparkline, F&O info).
  - **Click** opens a pop-up "quick chart" with buttons for OI, volume, basis and IV trends of that contract.
  - **Keyboard shortcuts** toggle column groups. The underlined letter is the key; for example, "P" cycles price columns.
  - **Saved views** recall a layout and its settings as a one-click macro.
- **Refresh:** "1-min live refresh"; F&O snapshots every minute; OI every 3 min (pricing page). "Auto-refresh fetches incremental ticks and updates only changed data points" (Features).
- **Alerts and backtests run locally on the user's PC** (pricing page).

### 1.2 Options screens (from the official helpdesk unless noted)

**putcall:** described as the "one stop place" for options activity on one symbol.
- A bar graph with **one bar per option, across strikes**. Calls and puts are shown together; a mirrored or side-by-side layout is inferred from the name and screenshots.
- The metric is selectable: price, OI, volume or IV, shown as an absolute value, a change or a % change.
- The change window can be custom intraday (5, 10 or 15 min, or N min) or D/W/M.
- **Multiple expiries overlaid** (0–4 weeks or months ahead).
- An **automatic max-pain marker** sits on the strike axis.
- Hover shows a tooltip; click opens a quick chart.

**chain:** the classic call | strike | put table with extra F&O columns (OI, IV, volume, VWAP, premium).
- "Intelligent color heatmaps" highlight notable cells.
- Optional **sparklines per cell or row**.
- Shows change or % change over a selectable interval, and multiple strikes and expiries in one view.

**matrix:** a **cross-tab grid of small charts or sparklines**, with strikes on one axis and parameters (price, OI, volume, IV) or timeframes or expiries on the other. The helpdesk pitches it as a way to "watch option writers adjust positions live: short covering / short build-up".

**maxzone:** a one-row-per-symbol summary table. Columns:
- Put OI, Call OI, Chg, PCR-OI
- **Max pain %** (distance from futures)
- **Max put distance %** and **Max call distance %** (the highest-OI strike and its % distance)
- **Max put buildup(+)** and **Max put unwind(−)**: the strike with the largest OI add or cut today, and the amount
- Max call buildup(+) and Max call unwind(−)

Options on this screen:
- A strike-range limiter (selected strikes or all), and units in shares, notional or value.
- A **delta-weighted view**: `weighted OI = OI × (1 − |0.5 − |delta||)`, which up-weights near-ATM OI and discounts deep ITM and far OTM strikes.

**flow, profile, volatility, wizard, spreads, screener:** menu names only. No public documentation was found.
- *flow* is probably option money flow or volume flow.
- *profile* is probably an OI/volume profile by strike. "OI_profile" is also listed as a chart indicator.
- *volatility* is probably IV, HV and IVP views.
- *wizard* is the strategy recommender ("suggests strategies from your market view [Bullish/Bearish/Flat/Volatile], risk appetite, target/stop"), per Features.

All of these are inferences from names.

**strategy:**
- Templates: STRADDLE, STRANGLE, VERTICAL, BUTTERFLY, CALENDAR and COVERED.
- Leg builder: call/put/future/stock, strike stepping, ITM/OTM filter, expiries w1–w3 and m1–m3.
- Live payoff, **what-if** analysis (price, IV and days per leg), Greeks and risk-reward.
- "Kite trade this" button.

**Multi-strategy scanner:** runs a strategy across symbols and strikes.

**Pairs:** correlation and z-score bands with Buy/Sell/Exit signals.

**positions/portfolio:** live MTM by symbol and by strategy, with Greeks. Kite trade-file import.

### 1.3 Markets screens
- **wall / Markets snapshot.** "wall" is the default landing hash. The helpdesk calls it the Markets screen, "a snapshot of the entire market".
  - It is a wall of top-N boxes: price gainers and losers, OI risers and fallers, volume spikes and most active, IV, delivery %, rollover %, VWAP %, basis, and most active, gaining and losing calls and puts.
  - **+/- on hover** changes how many bars each box shows.
  - Click any row for a quick chart.
  - Features calls it "a one-stop page of widgets that update together", with an "add widgets" control.
- **heatmap:** every symbol coloured by F&O buildup class (Long Buildup, Short Buildup, Long Unwinding, Short Covering).
  - LB/SC/LU/SB buttons re-sort the map.
  - A TopX slider limits it to the top movers.
  - It accepts a **custom filter expression**, for example `ABS(price%) > 1 and oi% > 5`.
- **adv/dec and sectors:** sector-level averages of price, OI, volume, PCR and rollover over intraday or D/W/M windows.
- **bubbles, turnover, fii:** FII/DII cash and derivatives statistics, plus bubble charts. Bubbles is inferred to be a scatter of % price vs % OI.
- **scans and screener:** a query builder of the form Data → Function → Candles → Offset → operator → Value.
  - Operators: `>=`, `<=`, `==`, `!=`, `<>` (inside), `><` (outside), `>>`, `<<`, `~~` (any of).
  - Also offers a free-text code editor and saved scans.
- **AUTO rankings / "X Score ratings":** a system composite of price, volume, technicals and F&O trends that emits Buy/Sell during market hours.

### 1.4 What is behind the paywall
- **Everything that shows data needs login.** No free tier is listed. There is a week trial.
- **Retail plans** (`myfno.app/pricing.html`, read directly):
  - Pro and Max both show ₹499 (struck-through ₹1999). Billing period is not stated; Month, Half and Year options exist, with roughly 30% and 50% off.
  - Same feature list on both: "1-min live refresh, intraday % changes (5/15/60min), multi timeframes/groups/views, custom combo scans, save views/watchlists, chart drawings, alert signals, X Score ratings".
  - Pro limits: 5 watchlists, 100 chart alerts, 5 group alerts, 20 backtests/day on 1 yr of EOD. Max is unlimited, with 5 yr of EOD backtests.
  - A ~50% discount runs until 11/11/2026.
- **Business plans:** ₹55k (Pro) and ₹77k (Max) + GST per year.
- **Data cadence:** 1-min snapshots; OI every 3 min. **Non-refundable.**
- **[2nd]** Strike.money says there is no free tier and you need Pro "to even explore", and gives a 4.3/5 rating. The old helpdesk references BASIC, GOLD and GOLD+ tiers.

### 1.5 Why traders find MyFnO compelling or sticky
1. **Density plus uniformity.** Every screen uses the same metric tabs, the same interval selector and the same hover-and-click behaviour. Once learned, every screen reads the same way.
2. **The "change over the last N minutes" lens is everywhere,** not just "change since open".
3. **Drill-down without context loss:** a hover tooltip, then a click to a quick chart, then buttons to switch to OI, IV or basis.
4. **Keyboard toggles and saved views** make it fast for power users.
5. **Pre-digested summaries** (maxzone's "max buildup or unwind strike", buildup heatmap classes) remove arithmetic from the trader's head.
6. **A user-programmable filter and alert language** with local execution.
7. A long track record (since 2001) and a cheap retail price.

---

## 2. iCharts (icharts.in/opt), by iCharts Technologies Pvt Ltd (2007), co-branded with the broker Tradejini

### 2.1 Overall shape
- The landing page `opt/index.php` renders only a toggle menu and a footer without JS. **All tool pages show a login form.** Their promotional text says:
  - "real-time tools"
  - "TradingView with up to 8 charts on one page"
  - "trade from the option chain"
  - "zero API charges"
  - First month paid; the next month is free if you meet a minimum trade count with the broker.
- The full catalogue below is from `Tools_at_a_Glance.php` (read directly). Descriptions come from the official docs, iCharts YouTube descriptions, and **[2nd]** the Twitter threads and Strike.money.

### 2.2 Tool catalogue with descriptions

**Options tools**

| Tool | What it shows (source) |
|---|---|
| Options Chart | An intraday price chart of a single option, with indicators and template save (docs). |
| Options Chain | Chain plus Greeks. Has toggles for **Trend, Buildup and VWAP** columns: whether each strike is above or below its VWAP, and its OI buildup class [2nd, rattibha 2022]. Lets you trade from the chain via a broker. |
| Options Chain – Old / **Option Chain – Min-by-Min** | Min-by-Min is inferred from its name and from the Date field docs: a chain you can **step through minute by minute, including historically** (data back to Aug 2018). |
| **Gamma Exposure (Beta)** | A strike-wise GEX profile. Name only; behind login. |
| **Premium Decay** | How much CE and PE premiums have decayed or expanded since a reference time, across strikes. Name plus [2nd] mentions; a live version is listed under Live Tools. |
| Open-High / Open-Low | Contracts where open equals the day's high or low. |
| **Option OI Stats** | **Bar chart of total OI and change in OI per strike**, filterable from near-ATM to all strikes. Historical expiry is available for study [2nd]. |
| **Option Snapshot** | Chain plus small charts of price and OI per strike in one view, to "see where OI change is occurring across many strikes quickly" [2nd]. |
| **Options OI Breakup** | Per-strike intraday OI change in user-chosen intervals (3, 5, 10, 15 min). "Written summaries of OI buildup refreshed every 3 min" [2nd]. Scalpers like it. |
| **Price vs OI** | For one or two strikes: price, OI, **PCR, ATP/VWAP and IV** on one chart (YouTube description). |
| **Multi Strike OI** | Line chart of OI (or OI change) for several chosen CE and PE strikes over the day, often with the index overlaid [2nd]. |
| **Cumulative OI Change** | Total call vs put OI change across the chain over the day; can be limited to near-ATM [2nd]. |
| **Total PE-CE OI Diff** (and "New") | An intraday line of (ΣPE OI − ΣCE OI), near-ATM only or all strikes. Called "the most popular feature, experts use it heavily" [2nd]. Sign flips and widening are the readings (Tradejini blog). |
| **Multi Strike PCR** | PCR per strike or strike band over time (inferred from name). |
| Max Pain | Expiry max-pain strike. |

**IV tools**

| Tool | What it shows |
|---|---|
| Volatility Skew | IV across strikes (smile/skew). |
| IV Chart | Intraday or historical IV of a contract. |
| IV-HV Chart | Implied vs historical (realised) volatility. Used "to choose long vs short gamma" [2nd]. |
| IVR-IVP Chart and IVR-IVP Scan | IV rank and IV percentile vs the past year, and a scan of all F&O names. |

**Strategy tools**

| Tool | What it shows |
|---|---|
| Straddle Charts, Straddle Charts Plus, Straddle Charts (TradingView) | A combined CE+PE premium chart for chosen strikes, with indicators. Users often add the VWAP of the straddle. CE and PE OI indicators can be merged into one pane to see crossovers (docs). Data back to Aug 2018; refresh "~1 min on average". |
| **ATM Straddle Chart** | A **continuous ATM straddle** whose strike rolls with spot (inferred from name). |
| Straddle Snapshot / Straddle Watch | A table of straddle premiums across strikes and expiries, with change. |
| **Multi Straddles / Straddle Combo Charts** | Several straddles or strangles overlaid on one chart. |
| Spread Chart, Butterfly, Iron Condor / Iron Fly, Double Calendar / Diagonal | Price charts of multi-leg structures. |
| Strategy Builder (Beta) | Payoff builder. |

**Futures tools (relevant to the heavyweights)**

| Tool | What it shows |
|---|---|
| Futures OI Buildup | Long buildup, short buildup, short covering or long unwinding, refreshed every 3 min. |
| OI Scan | A user-criteria scan. |
| Scrips in Uptrend / Downtrend | Trend scan. |
| Volume / OI / OI Chg Spikes | Spike scan. |
| Heatmap | Price and OI buildup across all F&O names. |
| Daywise Price & OI | Daily summary and details. |
| Participant-wise OI dashboard and trends | FII, DII, Pro and Client OI from the NSE end-of-day file. |
| Others | Rollover, Sector Summary, Support/Resistance Scan, Futures Preopen. |

**Live tools** ("requires broker login"): real-time versions of Option Chain, Premium Decay, Strategy Builder, TradingView charts, Price vs OI, Straddle charts, Multi-straddle, Price & OI Summary, Futures OHOL, Futures OI Buildup, Option OI Stats and Multi Strike OI.

**Platform conventions (official docs)**
- Every tool has a **Date field**. It defaults to today; setting a past date replays history and lists that day's expiries. This makes everything doubly useful for post-mortems and backtests.
- **Indicator templates** are saved per chart type ("Save Studies & Pref").

### 2.3 What is behind the paywall
- **All tools require login.**
- **[2nd] Strike.money pricing:**
  - ₹199 for a 7-day trial; ₹599/month; ₹1,600/quarter; ₹3,000/half-year; ₹5,700/year.
  - Basic users reportedly get **delayed data (~1.5 min price, ~4.5 min OI)**.
  - Real-time "Live Tools" need a linked broker (Tradejini, AC Agarwal, Upstox, Angel One, FYERS).
  - Upstox basic is limited to 2 live tools at once.
  - The subscription is free for a month if you trade enough via Tradejini or AC Agarwal.
  - Rated 3/5, with complaints of lag or crashes on volatile days.

### 2.4 Why traders find iCharts compelling or sticky
1. **One narrow question per tool.** "Is PE OI beating CE OI right now?" is a single line chart. Twitter educators share screenshots of these simple charts, which creates social proof.
2. **Straddle charts are the culture.** Indian option sellers (and buyers watching for expansion) live on the ATM straddle chart and its VWAP. That one chart says whether premium is being sold or bought.
3. **History in every tool** (back to 2018), via one Date field. Traders replay gap days and expiry days.
4. **Strike-level OI over time** (Multi-Strike OI, OI Breakup at 3–15 min) turns OI from a static snapshot into a story.
5. Cheap, and free if you trade via partner brokers.

---

## 3. Mapping ideas onto ApexOptions

**What ApexOptions already has:**
- ATM±2 ladder with LTP, bid/ask, delta, IV, vol/s, OI change, standing buyers and sellers, and drain classes
- Trigger panel: futures 15-s impulse z, heavyweight synchrony, episode type and first mover
- Heavyweights domino grid
- OI walls and PCR, with room to the next wall
- Force detector at levels
- Paper positions, a variant leaderboard and an event tape

**Data available:**
- Breeze ticks for about 120 instruments: spot, futures with 5-level depth, weekly ATM±12, next-week ATM±4, 23 heavyweights (cash and futures), BankNifty and FinNifty
- REST chain every 90 s (OI per strike)
- VIX

**Lens:** for a weekly option *buyer*, the enemies are **premium decay and IV crush while waiting** and **entering into writers' strength**. Ideas score high if they show, within seconds, whether option premium is currently being **bid (expansion)** or **sold (compression)**, and whether writers on the side the buyer is targeting are **covering (fuel)** or **adding (wall)**.

Breeze option ticks may carry an OI field. If so, OI-based ideas can update faster than 90 s. **Verify in the tick payload**; otherwise treat OI ideas as 90-s resolution.

### 3.1 High priority

| # | Idea | Source | Why it helps a buyer | Data supported? |
|---|---|---|---|---|
| H1 | **Continuous ATM straddle line plus straddle VWAP**, with a "straddle vs its VWAP" state chip (EXPANDING / COMPRESSING) and a 1-min and 5-min slope. The strike rolls with spot; show a roll marker. | iCharts ATM Straddle Chart, Straddle Charts plus VWAP culture | This is the single best "is premium being bought or sold right now" gauge. A buyer wants to enter when the straddle is above its VWAP and rising: decay is being outrun, and moves are paying. When the straddle bleeds below VWAP, directional moves get eaten by IV and theta. That is a veto signal for the trigger panel. Not eye candy. | **Yes.** Weekly ATM CE+PE ticks. Compute VWAP from tick volume deltas (or Breeze ATP if present). |
| H2 | **Per-strike "own-VWAP" column in the ladder:** option LTP vs that option's intraday VWAP, as a ±% badge, plus a 5-min sparkline. | iCharts Option Chain "VWAP/Trend" toggles; MyFnO chain sparklines and matrix | A buyer's CE above its VWAP means intraday buyers of that contract are in profit and holding: a better entry than one below VWAP, which signals writers' control. A sparkline shows acceleration vs fade faster than numbers can. | **Yes.** Tick volume and LTP per option. |
| H3 | **Per-strike buildup class from price Δ × OI Δ** over a selectable window: Long Buildup / Short Buildup / Short Covering / Long Unwinding, as a coloured tag in the ladder next to the drain class. | MyFnO heatmap (LB/SB/SC/LU), iCharts Futures and Options OI Buildup, MyFnO matrix "watch writers cover" | For a CE buyer, **CE short covering** (price up, OI down) is fuel. Writers are forced buyers, so moves extend. **CE short buildup** (price down, OI up) means writers are defending; skip. It is complementary to the order-book drain classes: drain shows the book, buildup shows positions. | **Partly.** OI is at 90-s REST (or tick OI if present). Price comes from ticks. Needs a window of at least 3 min to be meaningful. |
| H4 | **Universal interval selector (1/3/5/15 min/day)** for every "change" column (OI change, IV change, premium change, PCR change), not just since-open. | MyFnO everywhere; iCharts OI Breakup intervals | "OI added since 9:15" hides what writers did in the last 5 minutes, which is what matters for a scalp. One global hotkey to switch windows is cheap and high value. | **Yes.** Needs a ring buffer of snapshots. OI windows smaller than 90 s are not possible without tick OI. |
| H5 | **Futures (and heavyweight futures) OI buildup state on the domino tiles**: LB/SB/SC/LU over a rolling 3–5 min, plus Nifty-futures buildup in the trigger panel. | MyFnO heatmap; iCharts Futures OI Buildup and Heatmap | Separates impulses driven by **fresh longs** (Long Buildup, sustainable) from **short covering** (fast but can exhaust) and **long unwinding** (fake strength). It adds a second, independent axis to the synchrony score. | **Yes.** Futures ticks carry OI on NSE feeds; verify in Breeze. Otherwise use quotes REST. |
| H6 | **Delta-weighted near-ATM PCR and wall strength**, using MyFnO's weight `OI × (1 − |0.5 − |δ||)`, shown next to raw PCR. Optionally also "max CE buildup / max CE unwind strike today and in the last 15 min" (MyFnO maxzone). | MyFnO maxzone | Raw PCR is dominated by far-OTM lottery strikes. Weighting near-ATM OI tells the buyer where **relevant** writers sit. "Max CE unwind strike in the last 15 min" names the wall that is crumbling, which is exactly where breakout buyers want to be. | **Yes.** REST chain OI plus the deltas you already compute. |
| H7 | **CE vs PE premium-decay panel:** % change of the summed CE premium (ATM±2) vs summed PE premium since the session reference and over the last 5 min, as two diverging bars. | iCharts Premium Decay | Shows which side the market is paying for. If CEs hold value while spot is flat, that is call demand: a leading tell for CE buys. If both bleed, it is a no-trade (seller's) day. It also helps the buyer avoid buying the side whose premium is being dumped. | **Yes.** Ticks. |

### 3.2 Medium priority

| # | Idea | Source | Why / caveat | Data supported? |
|---|---|---|---|---|
| M1 | **Total PE − CE OI difference line** (near-ATM ±5 and all strikes) over the day, with sign-flip markers on the event tape. | iCharts Total PE-CE OI Diff and Cumulative OI Change | Popular and intuitive. It is a slow, regime-level read (who is writing), not an entry trigger. Good for the buyer's directional bias for the session; a sign flip is an event worth taping. | **Yes**, at 90-s resolution. |
| M2 | **Multi-strike OI lines:** OI over time for the nearest CE wall and PE wall (and ±1 strike), with spot overlaid. | iCharts Multi Strike OI; MyFnO matrix | Shows a wall **forming or dissolving** over time. Your OI-walls tile shows only the current state. "Wall OI falling for 3 consecutive snapshots" is a good confirmation for a breakout buy. | **Yes** (90 s). |
| M3 | **Mirrored put/call bar strip by strike** (PE bars left, CE bars right, ATM±12), switchable between OI, OI change over the window, volume over the window and IV, with a spot marker. | MyFnO putcall; iCharts Option OI Stats | Faster for the eye than a table for spotting where the action concentrates. It is a visualisation of data you already have, so its value depends on the window toggle (H4). It partly duplicates the walls tile, and a static version is eye candy. | **Yes.** |
| M4 | **ATM IV line with realised-vol band** (IV vs a 15-min or 30-min realised vol of futures) plus a VIX overlay. Optionally IV percentile vs your own stored history. | iCharts IV, IV-HV, IVR-IVP; MyFnO HV/IVP | A buyer wants **realised > implied** (moves outrunning priced vol). A widening IV−RV gap means you are overpaying. IVP needs weeks of stored history before it means anything. | **Yes** for IV/RV/VIX. IVP needs logging. |
| M5 | **What-if box for the selected long option:** "if NIFTY +X pts in T min with IV ±Δ, premium ≈ …" giving target and stop in index points vs premium. | MyFnO strategy what-if | Turns a futures-level target (the next wall / room to wall) into a premium target and R:R before entry. That is useful discipline for a buyer. | **Yes** (Black-Scholes with live IV). |
| M6 | **Chain replay / Date-field scrubber:** a time slider that re-renders the ladder, walls and tiles at any past minute from your own logs. | iCharts Option Chain Min-by-Min plus Date field everywhere | Huge for post-mortems and variant tuning (why did HAWK enter there?), and sticky. Not a live-decision aid. | **Yes,** if ticks and snapshots are persisted. |
| M7 | **Futures basis line** (futures − spot) and its 5-min change. | MyFnO Basis column | Basis widening during an up-impulse indicates genuine futures buying, not spot-only noise; it confirms the trigger. | **Yes.** |
| M8 | **User rule language and alerts on the event tape**, for example `ce_atm.vwap_dev>2% and ce_wall.oi_chg_5m<0`. | MyFnO custom filter and scan builder | Lets the trader codify setups without code changes. Medium, because ApexOptions already has engineered triggers. | **Yes.** |
| M9 | **Weekly vs next-week IV (term structure)** chip for ATM. | MyFnO multi-expiry putcall | When near-week IV is far above next-week IV, an event premium is priced in, and buyers face a crush risk after the event. | **Yes** (next-week ATM±4). |
| M10 | **Hover-tooltip and click-to-quick-chart** on every ladder row and tile (price, OI, IV and own-VWAP, last 30 min). | MyFnO interaction model | A speed-of-investigation gain without cluttering the main view. This is UX, not signal. | **Yes.** |
| M11 | **Spike detector** for option volume/s and OI change outliers, as a z-score per strike. | iCharts Volume/OI/OI Chg Spikes | Probably overlaps with vol/s and drain classes; worth adding only as a tape event. | **Yes.** |
| M12 | **Gamma-exposure-by-strike strip** (assume writers are short gamma), marking "pin zones" vs "acceleration zones". | iCharts Gamma Exposure (Beta) | In India, OI holders are mostly retail and prop writers rather than dealers, so GEX is a **heuristic**. Still, high short gamma near ATM on expiry day explains pinning and squeezes. Label it as experimental. | **Yes** (OI plus computed gamma). |

### 3.3 Low priority / eye candy

| # | Idea | Source | Why low |
|---|---|---|---|
| L1 | Max pain marker | Both | Relevant mainly to sellers near expiry close. Weak intraday signal for a buyer. A small chip on expiry day is enough. |
| L2 | Volatility skew chart | iCharts | Interesting, but rarely changes a buy decision within minutes. A put-skew steepening alert could live on the tape. |
| L3 | Multi Strike PCR | iCharts | Redundant with the walls tile and H6. |
| L4 | Straddle Watch tables, multi-straddle overlays, butterfly / iron condor / calendar charts | iCharts | Seller-oriented. H1 covers what a buyer needs. |
| L5 | Strategy builder / recommender / payoff for multi-leg, pairs | MyFnO | Out of scope for CE/PE-only buying (M5 covers the single-leg case). |
| L6 | Sector adv/dec, FII/DII and participant-wise OI, rollover, delivery | Both | End-of-day or monthly data. Context at the start of day at most. |
| L7 | Auto rankings / "X Score" composite signals | MyFnO | ApexOptions already has conviction and variant scoring. A third composite adds confusion. |
| L8 | 8 TradingView charts on one page, themes, server switcher, trade-from-chain | Both | Eye candy or out of scope (paper trading). |
| L9 | Open-High / Open-Low scan on heavyweights | Both | Mild context for the domino grid; cheap to add as a tile badge if wanted. |

### 3.4 UX lessons worth copying regardless of features
1. **One question per panel** (iCharts), instead of several dense numbers per tile. For example, make H1's chip answer only "is premium being bought?"
2. **Same controls everywhere** (MyFnO): one global interval hotkey (H4) and one hover/click behaviour (M10).
3. **Keyboard toggles for column groups and saved layouts**, such as a "scalp view" vs a "context view".
4. **History via one date or time scrubber** on every panel (M6). This is what keeps iCharts users returning after hours.

---

## 4. Sources

**First-party, read directly**
- https://www.myfno.com/#wall (app shell)
- https://www.myfno.com/pricing → https://myfno.app/pricing.html
- https://myfno.app/
- https://www.myfno.com/Launch
- https://www.myfno.com/Features
- https://www.myfno.com/Support
- https://www.myfno.com/Videos
- https://help.myfno.com/
- https://help.myfno.com/en/article/putcall-1mu71by/
- https://help.myfno.com/en/article/option-chain-1czorov/
- https://help.myfno.com/en/article/matrix-xtqga7/
- https://help.myfno.com/en/article/maxzone-ze602b/
- https://help.myfno.com/en/article/markets-15zpj10/
- https://help.myfno.com/en/article/heatmap-1xzhlyj/
- https://help.myfno.com/en/category/strategy-1j0a5hm/
- https://www.icharts.in/opt/index.php (footer only)
- https://www.icharts.in/opt/Tools_at_a_Glance.php
- https://www.icharts.in/opt/Documentation.php
- https://www.icharts.in/opt/About_us.php
- https://www.icharts.in/opt/MultiStrikeOI.php and https://www.icharts.in/opt/StraddleCharts.php (login wall)

**Secondary [2nd]**
- iCharts YouTube descriptions:
  - https://www.youtube.com/watch?v=PDvHnh5cR3M (tools intro)
  - https://www.youtube.com/watch?v=Lrwt6fxPJhI (Price vs OI)
- Twitter threads mirrored on rattibha:
  - https://en.rattibha.com/thread/1564663629244497921
  - https://en.rattibha.com/thread/1583677032470151168
- Strike.money reviews (competitor-authored):
  - https://www.strike.money/reviews/myfno
  - https://www.strike.money/reviews/icharts
- Tradejini blog on the CE-PE OI difference: https://www.tradejini.com/blogs/a-practical-guide-to-ce-pe-oi-difference
- Stockmaniacs on multi-strike OI (generic, Sensibull-based): https://www.stockmaniacs.net/unveiling-the-power-of-multi-strike-oi-chart/

**Could not read:** iCharts pricing page (fetch error), all iCharts tool pages (login), MyFnO screen contents (login), the MyFnO flow/profile/volatility/wizard/screener docs (none public), YouTube playlist titles (bot wall), buzzchronicles thread (server error).
