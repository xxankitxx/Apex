# G5 — Data Platform & Latency

*Working Group G5 of the ApexOptions design team. Chair's record of the working session, Saturday 17 October 2026.*
*Tags as in the brief: **[FACT]** verified in code/docs/measurement (source named) · **[OWNER]** · **[ANALYSIS]** · **[HYPOTHESIS]**. Sources are listed at the end.*

---

## 1. Members and their lenses

- **Ingrid Svensson** — low-latency systems: process isolation, shared memory, seqlocks; "a number you did not measure is a guess".
- **Pranav Kulkarni** — Python on Windows: what `breeze_connect`, `python-socketio`, `pyzmq`, `shared_memory` and `asyncio` actually do; what spawn/no-fork/no-uvloop costs.
- **Jae-won Park** — real-time front end: binary WebSocket, typed-array state, canvas at the refresh rate, latency you can see on screen.
- **Olivia Grant** — SRE/observability: watchdogs, failure catalogues, recorders, deterministic replay, runbooks; "if it can fail silently, it will, and it did".

## 2. What we were asked

**[OWNER]** *"I want my system to be superfast and as such the tick-by-tick display is paramount for me. I don't want any delay there. So this should be your primary focus point even before you start coding."* · *"Do not use stale data over a period of time."* · Track ~65–70 stocks + 3 indices (cash, futures, options/OI) under Breeze's 100 calls/min and 5,000 calls/day REST limits.

**[ANALYSIS]** Our reading, in priority order:

1. **Latency is a product feature measured on screen.** "No delay" becomes a number with an alarm (§5.7), not a feeling.
2. **Staleness is the second enemy.** MYTHOS failed stale in ways that *looked alive*: a dead session with cached prices, a REST chain frozen three hours with zero exceptions, a heavyweight silent in 184,071 frames because of a corrupted token (feed.py `_clean_token`). Every value here carries its own age; the platform alarms on age and silence, not on exceptions.
3. **The tick path shares a GIL with nothing that thinks.** MYTHOS ran 1–3 s analytics passes in the socket's process and starved its own exit thread in replay (tape_feed.py). Sockets live in processes that do nothing else.
4. **The REST budget is a shared, persisted resource** that orders draw from; it must survive restarts and degrade gracefully.
5. **A recorded day must drive the whole system again, deterministically** — the force/pressure/domino thresholds (G1–G3) are calibrated on ticks, not on 1–2 s frames.

## 3. Ideas by member

### Ingrid Svensson — isolate, then measure
- **One FEED process per Breeze socket.** Each owns one socket, writes a disjoint row range of the shared table and publishes on its own PUB endpoint. A crash, GC pause or reconnect on the basket socket cannot queue a Nifty tick; the hero socket carries the fewest feeds (≈60) so its receive loop is never behind.
- **The shared table is the truth; ZeroMQ is the doorbell.** One fixed-layout shared-memory table, one 256-byte row per instrument, a per-row **seqlock** (writer bumps `seq` to odd, writes, bumps to even; readers copy and re-check). Every-tick consumers subscribe; latest-state consumers read the table. Nothing waits on a lock.
- **Prove the budget in-process.** Stamp `perf_counter_ns()` after `recv()` returns and after the publish; keep the deltas in a ring buffer in the control block; publish p50/p99/max per second and show it. Indicative measurement today (Linux container, Python 3.13.16; re-run on the owner's box) **[FACT, measured]**: orjson decode of a 185-byte tick 1.4 µs; token→row lookup + 21-field `struct.pack_into` 0.6 µs; seqlock write to shared memory 0.5–0.8 µs; pyzmq PUB send 6.6 µs → **≈ 12 µs per quote tick, ≈ 18 µs per depth tick.** Spawning one thread costs ≈ 100 µs on this box — which is what the SDK path does per tick (Pranav).
- **A lag canary.** Subscribe Nifty futures on two sockets and compare arrival times; if one trails by > 500 ms the broker is queueing that socket — alarm and swap roles. The only way to see broker-side lag that `ltt` (whole seconds, below) cannot show.
- **Lockstep replay** for determinism: REPLAY-FEED advances only after every consumer acknowledges the batch; two runs must hash identical.

### Pranav Kulkarni — what the libraries actually do ([FACT], from source read this session)
- **`breeze_connect` 1.0.69.** `import breeze_connect` synchronously downloads `SecurityMaster.zip` and attaches DEBUG file loggers in the CWD (`breeze_connect.py` 26–56). `ws_connect` builds a default `socketio.Client()`, `transports="websocket"`, `wait_timeout=3`, and **wraps every connect exception into the bare string "Failed to connect to live stream"** (71–88) — the TLS/auth/timeout reason is discarded. `subscribe_feeds` returns `"Exception while subscribing to feeds …"` instead of raising (435); `watch()` just emits `join` and requests no acknowledgement (134–149), so a rejected token is invisible to the client. `ws_disconnect` only `emit("disconnect", …)`; it never closes the WebSocket (91). The wire tick is a JSON **array**; `parse_data` maps positions (NSE equity len 21; NFO len 23 with `OI` at [12], `CHNGOI` at [13]) and converts the exchange time with `datetime.fromtimestamp(x).strftime('%c')` — **exchange time reaches us as a locale string at 1-second resolution** (789–805). Depth is a *separate* message on token `4.2!<tok>` with its own `time`, eight fields per level including `BuyNoOfOrders`/`SellNoOfOrders` for exchange '4' = NSE and NFO (553–561) — the SDK *parses* order counts; whether the server fills them is the probe's job. REST uses module-level `requests.get/post` with **no `Session` and no timeout** (1147–1163): a TLS handshake per call, and a call can hang forever. Order notifications come from a third host, `livefeeds.icicidirect.com` (`config.py` 10).
- **`python-engineio` 4.14.0** dispatches every incoming MESSAGE with `run_async=True` → **a new `threading.Thread` per tick** (`client.py` 428–436, 472–477, 155): ~100 µs/tick, no ordering guarantee between ticks, and MYTHOS's "single writer" was really hundreds of short-lived writers — it never checked ordering.
- **`websocket-client` 1.9.2** builds `ssl.SSLContext(PROTOCOL_TLS_CLIENT)` + `load_default_certs()` unless `ca_certs` or `WEBSOCKET_CLIENT_CA_BUNDLE` is given (`_http.py` 253–282, 345–370). On Windows that means the **CA and ROOT system stores read by OpenSSL** (Python docs) — not certifi — and OpenSSL fetches no missing intermediates. A context can be injected via `socketio.Client(websocket_extra_options={"sslopt": {"context": ctx}})` (`engineio/client.py` 351).
- **Proposal: own the socket.io protocol** over `websocket-client`: `0` open, `40{auth}` connect, `42["stock",[…]]` events, `42["join",[tokens]]`, `2`/`3` ping/pong, `41` disconnect — one blocking `recv()` loop per socket, `orjson`, no threads per message, ordering preserved, raw epoch `ltt`. Keep the SDK path behind a flag; A/B it in the probe.
- **Windows specifics.** Python 3.13's `time.time()` uses `GetSystemTimePreciseAsFileTime`; `monotonic()`/`perf_counter()` use QPC (Python docs, "Changed in 3.13") — sub-µs stamps exist *because* the owner runs 3.13; preflight asserts the resolution. Processes launch via `subprocess.Popen([sys.executable, "-X", "utf8", "-m", "apex.<role>"])`, never `multiprocessing.Process`. `zmq.asyncio` rejects the Windows Proactor loop ("does not implement add_reader … Use WindowsSelectorEventLoopPolicy", pyzmq 27.2 `asyncio.py`) → the GATEWAY uses `websockets.sync.server` (threads; websockets 17.2) and no asyncio at all. `ipc://` needs Unix domain sockets (libzmq docs) → `tcp://127.0.0.1`. `SharedMemory.unlink()` is a no-op on Windows; the block dies with its last handle (Python docs) → the SUPERVISOR creates it and holds it all day. REST: monkeypatch `ApificationBreeze.make_request` onto a persistent `Session` with `timeout=(3.05, 10)`, keeping the SDK's checksum logic (1131).

### Jae-won Park — the screen is the product
- **Binary frames, one schema.** The browser mirrors the table: an `ArrayBuffer` (512 × 256 B = 128 KB) with typed-array views generated from a schema message. A tick frame is the raw row bytes; applying it is a 256-byte `set()`. No JSON, no parsing, no allocation per tick — "GATEWAY computes nothing" is literal: it forwards bytes.
- **Two WebSocket connections:** `/ws/hero` (per tick, Nifty complex) and `/ws/basket` (coalesced 50–100 ms, metrics, events). TCP has no priority; a 40 KB basket frame must never sit in front of a hero tick.
- **Render at the refresh rate, draw what changed.** rAF loop; ladder, futures book and sparklines on canvas layers with per-row dirty flags; basket board canvas ≤ 10 Hz; the event tape is the only DOM list (append, cap 200). Tabular numerals; three age colours from `recv_ns` at paint time.
- **Three stamps, honestly labelled**: `ltt` (exchange, whole seconds), `recv_ns` (FEED), paint (rAF timestamp + `performance.timeOrigin`). The meter shows FEED→GATEWAY, GATEWAY→browser, browser→paint, and "EXCH→FEED ≈ 0–1 s". Same machine, same clock; a 1-Hz ping still proves the offset is ~0.
- **The number:** feed-receive→paint **p50 ≤ 10 ms, p99 ≤ 30 ms** for hero rows at 60 Hz (two frames is the honest p99 on Windows + Chrome); basket ≤ 150 ms. `PerformanceObserver('longtask')` logs any main-thread stall > 50 ms.
- **Background tab:** rAF is paused in background tabs [FACT, MDN]; `onmessage` keeps running so the mirror stays current; on `hidden` the page asks the GATEWAY to downgrade hero to coalesced 100 ms and suspends the meter; on `visible` it requests a SNAPSHOT. Alarms must not depend on the tab.

### Olivia Grant — assume it failed silently
- **Heartbeats in the table, not threads in a list**: every process writes `heartbeat_ns` every 250 ms; the SUPERVISOR restarts per policy; the screen shows every process's age.
- **One sequenced log per socket per day** as the recorder's truth (global order by sequence, append-only, hourly rotation, zstd on close); per-instrument columnar files are *derived*. 300 per-instrument files cannot tell you the order in which the market happened.
- **Record REST responses and order events in the same log** so replay serves chain, VIX and fills at the same virtual time as ticks.
- **The REST ledger is a database row, not a counter in RAM** — SQLite, one row per call, restart-safe.
- **Alarm channels independent of the browser**: SUPERVISOR audio (`winsound`) and a Windows toast; the browser banner is the third channel.
- **A fault-injection matrix is part of the build** (§6.5) and **a flight report at 15:32** (latency percentiles, drops, reconnects, budget, alarms, silent instruments).

## 4. The debate

| # | Question | Positions | What settles it | Decision |
|---|---|---|---|---|
| 1 | SDK socket or our own socket.io client? | **Pranav:** own it — ≥ 100 µs/tick thread spawn, reordering, hidden connect errors, `ltt` destroyed. **Olivia:** the SDK is the supported path; a protocol change breaks a hand-rolled client at 09:15. | Probe A/B on separate sockets: per-tick cost, `ttq` regressions, connect-error visibility. A shape canary (array length 21/23, token prefix, event name) alarms "PROTOCOL CHANGED" and flips to the SDK path. | **Own client**; SDK fallback behind one flag; canary mandatory. |
| 2 | Threads per socket or process per socket? | **Pranav:** threads are simpler; 12 µs ticks release the GIL at each `recv`. **Ingrid:** isolation is the point; GIL hand-off adds jitter at the open. | Synthetic 3-socket 10k msgs/s test: hero p99 threads vs processes. | **Process per socket** (FEED-0 hero, FEED-1 movers, FEED-2 rest). |
| 3 | Recorder: global log or per-instrument files? | **Ingrid:** per-instrument is lock-free and parallel. **Olivia:** cross-instrument order is the whole point for lead–lag work. | G1 confirms it needs cross-instrument order (it does). | **Global log per socket**; Parquet per instrument derived at EOD. |
| 4 | ZeroMQ for everything, or the table? | **Pranav:** `ZMQ_CONFLATE` could replace the table. **Ingrid:** table = state, ZMQ = events. | libzmq docs: `CONFLATE` keeps *one* message per socket, not per topic — useless for 300 instruments. | **Both.** |
| 5 | One browser WS or two? | **Pranav:** one with priority. **Jae-won:** TCP has no priority. | §6.3 fat-frame test. | **Two.** |
| 6 | The SLO number | **Jae-won:** p99 ≤ 16.7 ms. **Olivia:** that false-alarms daily on Windows. | 30 min at the open (§6.3). | p50 ≤ 10 / p99 ≤ 30 ms; amber p99 > 50 ms for 10 s; red > 100 ms or any gap > 1 s. |
| 7 | Replay: lockstep or timed? | **Ingrid:** lockstep or it is not deterministic. **Jae-won:** the UI must be rehearsed at real cadence. | Both are cheap once REPLAY-FEED exists. | **Both modes.** |
| 8 | Who owns the REST budget? | **Olivia:** one REST process, two lanes, one ledger. G6 may want the executor in its own process. | G6's answer on order-path isolation. | One budget object (control-block counters + SQLite) regardless of process layout. |
| 9 | Carry ≈100 stock-option feeds at all? | **Olivia:** cost without measured benefit; stock positioning is in futures OI per tick. **Ingrid:** cheap to carry; measure. | Probe stage C with and without them. | On FEED-2 only; dropped if load shows or G1/G2 do not use them. |
| 10 | What fixed 16 Oct? | §5.5: the saved file could not have been the mechanism. | Two checks on the owner's machine (§9). | Windows-store trust with AIA (`truststore`), pinned-bundle fallback, 5-second TLS diagnostic. |

## 5. Consensus proposal

### 5.1 What this platform is
A set of small single-purpose Windows processes that turn Breeze's socket.io feeds into (a) a shared-memory table of the latest state of every tracked instrument, with ages; (b) an ordered tick stream; (c) a binary tick stream to the browser with an on-screen latency meter; (d) an append-only recording that can drive the whole system again at any speed; (e) a budgeted REST scheduler — all supervised by watchdogs that alarm on *age* and *silence*.

### 5.2 A day in its life (IST)
- **08:45** Owner pastes the session token into the credential store (DPAPI-protected file, never a `.py`); runs `apex preflight` (§5.9): GO/NO-GO in < 60 s, ≈ 12 REST calls, token masked.
- **08:50** `apex start`: SUPERVISOR creates the shared table, writes `instruments.json` (≈65–70 names from the NSE constituent CSVs, tokens from the scrip master, expiries from the explicit English-month calendar), launches RECORDER → GATEWAY → ANALYTICS → REST → FEED-0/1/2. Browser opens; SNAPSHOT lands.
- **08:55** FEEDs connect (the TLS probe logs DNS/TCP/TLS/upgrade/CONNECT timings), `join` tier lists in batches of 50 tokens, start the first-tick watchdog.
- **09:00–09:08** Pre-open cash ticks turn rows from "awaiting first tick" to live.
- **09:15** Open burst; FEED histogram visible; hero ladder paints; meter live. The REST data lane starts at **09:16:00**, after the burst.
- **09:15–15:30** Steady state: ATM re-centring every 10 s (join new strikes; leave beyond ATM±8 unless held or hero); Tier-2 promotions; session probe every 5 min; disk check 12:00; alarms per §5.8; budget gauge on screen.
- **15:30** Ticks stop. **15:31** RECORDER closes/compresses. **15:32** Shredder writes Parquet; flight report. **15:35** `apex stop`: EXECUTOR flat-check → FEEDs send `41` + WebSocket close → reverse-order exit → table released.

### 5.3 Processes

```
              Breeze livestream (socket.io/TLS)                 Breeze REST
              S0 hero     S1 movers     S2 rest                     |
                 |           |            |                         |
              FEED-0      FEED-1       FEED-2             REST (order lane | data lane) + ledger.sqlite
                 \           |           /                          |
   +------------- SHARED TABLE shm "apex_v1" ------------------------+
   | control block | 512 x 256 B rows | metrics 512x64 | heartbeats | budget |
   +-----------------------------------------------------------------------+
        PUB tcp://127.0.0.1:560{0,1,2}   topic = class u8 + id u16, payload = row
            |             |             |                 |
        RECORDER     ANALYTICS-n     GATEWAY           EXECUTOR (order lane; notifications
        SUB all      SUB class       SUB 'H' + table    from livefeeds.icicidirect.com)
                                         |
                                  browser /ws/hero  /ws/basket
   SUPERVISOR: creates/holds table, launches/restarts all, watchdogs, audio + toast alarms
```

| Process | Does | May NOT | Restart |
|---|---|---|---|
| **SUPERVISOR** | Holds the table; launches children inside a Job Object (kill-on-close — nothing orphans a Breeze socket slot); heartbeats; watchdogs (§5.8); alarms; flight report; virtual clock in replay. | Touch sockets; decide trades. | Root process; if it dies the tree dies and the operator restarts. |
| **FEED-k** ×3 | Connect with our TLS context, auth, join/leave; `recv()` → orjson → pack row → seqlock write → PUB; per-tick µs histogram; reconnect with backoff; first-tick/silence tracking per row. | Log on the hot path; allocate beyond the packed row; call REST; import `breeze_connect`; compute anything about the market. | ≤ 1 s; if Breeze refuses because the dead socket's slot is held, backoff 2/4/8 s up to the measured hold time; other FEEDs unaffected. |
| **GATEWAY** | Serves the page; hero thread forwards 'H' rows per tick (ticks arriving mid-send batch into the next frame); basket thread every 50 ms copies rows whose `seq` changed + changed metrics + events; CLOCK each second; SNAPSHOT on connect. | Compute, parse or JSON-encode per tick; block the hero thread on a slow client (per-client queue, drop-oldest, counted). | ≤ 1 s; browser auto-reconnects and requests SNAPSHOT. |
| **ANALYTICS-n** (G1–G4) | SUB needed classes; write `metrics[i,m]` + `metrics_ts`; events on 'E'. | Write instrument rows; drop silently (RCVHWM per worker, drops counted). | Restart; metric ages show the gap. |
| **RECORDER** | SUB all + 'R' + 'O' → sequenced log; 64 MB buffer, flush 250 ms, rotate hourly, zstd on close; shredder at EOD. | Drop silently (RCVHWM 1,000,000; counter in control block). | Restart; the gap is a logged record. |
| **REST** | Token bucket, two lanes; data lane: chains/VIX/sisters/promotions; order lane: EXECUTOR (G6 logic) on a pre-warmed `Session` with timeouts + the notification socket; ledger; writes results to the table and 'R'. | Exceed 60/min on the data lane; retry without charging the ledger. | Restart; the ledger restores the budget. |
| **REPLAY-FEED** | Replaces FEED-0/1/2 and the data lane in replay: reads the log in sequence, writes rows/PUB identically, drives the virtual clock, serves recorded REST/order records at their virtual time; lockstep or timed. | Exist in live mode. | — |

**Startup order:** SUPERVISOR → table → RECORDER → GATEWAY → ANALYTICS → REST → FEEDs (no tick is ever unrecorded or unseen). **Shutdown:** reverse, EXECUTOR flat-check first, `41` + close on every socket; `atexit`, `CTRL_CLOSE_EVENT` handlers and `finally` all call the same disconnect.

**Crash recovery.** *Worker dies:* heartbeat > 2 s → restart; its metrics age. *FEED dies:* rows freeze → silence watchdog + heartbeat → restart; while a held slot blocks reconnection the screen shows "FEED-0 reconnecting, next try in n s" and the Nifty-futures canary on FEED-1 keeps the hero price alive. *Browser disconnects:* GATEWAY drops that client's queue; on reconnect SNAPSHOT + resume; no browser for 60 s in market hours → audio "NO DISPLAY". *GATEWAY dies:* restart; the page reconnects (0.5→4 s backoff).

**Windows constraints honoured:** spawn (independent `-m` entry points, nothing inherited), no uvloop (no asyncio on the tick path), Proactor/`zmq.asyncio` incompatibility (not used), 3.13 precise clocks (asserted), `-X utf8` everywhere and no emoji in logs, Job Object process-tree lifetime, shared-memory lifetime by handle count, timer resolution irrelevant on the hot path (blocking `recv`, no sleeps).

### 5.4 Row and message formats

**Instrument row (256 B, little-endian; one struct, four homes: table row, PUB payload, recorder record, WS tick frame).**

| Off | Type | Field | Off | Type | Field |
|---|---|---|---|---|---|
| 0 | u64 | `seq` (seqlock; even = stable) | 72 | u64 | `ttq` |
| 8 | u64 | `recv_ns` (FEED receive, epoch ns) | 80 | u64 | `tot_buy_q` |
| 16 | u32 | `ltt_s` (exchange last trade, epoch s) | 88 | u64 | `tot_sell_q` |
| 20 | u32 | `book_ts_s` (depth message time, epoch s) | 96 | f64 | `ttv` |
| 24 | f64 | `ltp` | 104 | f32×4 | `open, high, low, close(prev)` |
| 32 | f64 | `bid` | 120 | i32 | `chg_oi` |
| 40 | f64 | `ask` | 124 | f32×2 | `lower_ckt, upper_ckt` |
| 48 | f64 | `avg_price` | 132 | u16 | `flags`: has_quote, has_depth, trend_up, stale, replay, low_res_source |
| 56 | u32 | `bqty` | 134 | u8,u8 | `src_socket`, `last_msg_type` |
| 60 | u32 | `aqty` | 136 | 5×24 B | depth L1–L5: `bid_px f32, bid_qty u32, bid_ord u16, pad, ask_px f32, ask_qty u32, ask_ord u16, pad` |
| 64 | u32 | `ltq` | 256 | | end |
| 68 | u32 | `oi` | | | |

Monotonic guard in FEED: a quote whose `ttq` or `ltt_s` is below the row's is dropped and counted (`reorder_drops`) — possible only on the SDK path; on the raw client it signals a protocol change.

**Control block (4 KB):** magic/version, `n_rows`, mode, `virtual_now_ns`, `heartbeat_ns[16]`, per-socket state (`connected`, `msgs_per_s`, `last_msg_ns`, `backlog_flag`, `reconnects`), FEED hot-path stats per second (`count, p50_us, p99_us, max_us`), REST budget (`minute_count`, `day_count`, `reserve`), `alarm_bits`, `reorder_drops`, `recorder_drops`. **Metrics table:** `metrics[512,64] f32` + `metrics_ts[512,64] u64`, ids registered in `metrics.json` by G1–G4.

**PUB envelope (single part):** `class u8 ('H' hero, 'B' basket, 'E' event, 'C' control, 'R' REST response, 'O' order event) + id u16 + payload` (the row; msgpack for E/R/O). RCVHWM: RECORDER 1,000,000 (never drop), GATEWAY hero 10,000 (drop-oldest, counted), workers 50,000 (counted). PUB never blocks (libzmq drops when a subscriber's queue is full).

**Recorder record:** `0xA5, type u8 (1 quote, 2 depth, 3 control, 4 metrics, 5 event, 6 REST, 7 order), len u16, seq u64 (per socket), socket u8, pad, recv_ns u64` + payload (the row for 1/2). At 272 B/record: 500 msgs/s avg → 3.1 GB raw/day; 1,000/s → 6.1 GB; 2,000/s → 12 GB; zstd ≈ 5× on this data → 0.6 / 1.2 / 2.4 GB [ANALYSIS; the probe supplies the rate]. Above ~1,500/s we switch to compact 72/144-B quote/depth records. Retention proposal: 90 days of logs, Parquet forever.

**WS frames (binary):** header `type u8, count u16, gw_send_ns u64`; `0 SCHEMA` (JSON: row dtype, registry, metric ids, code hash — mismatch reloads the page); `1 TICK` (hero rows); `2 SNAPSHOT`; `3 COALESCED` (changed rows, ≤ every 50 ms); `4 METRICS` (`id u16, metric u8, value f32, ts u64` × n, 100 ms); `5 EVENT` (msgpack, with audio class); `6 CLOCK` (wall ns, heartbeat ages, socket states, FEED histogram, budget); `7 ALARM`.

### 5.5 Breeze ingestion plan

**Subscription tiers** [ANALYSIS from brief §5.2; feeds = token subscriptions, quotes and depth counted separately].

| Socket | Tier | Instruments | Quotes | Depth | Feeds | Rate (to measure) |
|---|---|---|---|---|---|---|
| S0 FEED-0 | 0 Nifty complex | NIFTY spot | 1 | – | 1 | 1–5/s |
| | | NIFTY near futures | 1 | 1 | 2 | 30–50/s (feed.py) |
| | | NIFTY weekly ATM±8 CE+PE; depth on ATM±2 (10 hero) | 34 | 10 | 44 | 100–500/s at the open |
| | | BANKNIFTY spot (CNXBAN) + near futures | 2 | 1 | 3 | 20–40/s |
| | | FINNIFTY spot + futures (**no working code as of 16 Oct [FACT]**) | 2 | – | 2 | – |
| | | NIFTY next-week ATM±2 CE+PE (rollover, G4 choice) | 10 | – | 10 | 10–50/s |
| S1 FEED-1 | 1 movers (HDFCBANK, ICICIBANK, RELIANCE, BHARTIARTL, LT, SBIN, AXISBANK, INFY, KOTAKBANK, M&M) | cash | 10 | – | 10 | 2–10/s each |
| | | near futures; depth on the 5 common banks + RIL; + Nifty futures canary | 11 | 6 | 17 | 1–5/s each |
| | | monthly options ATM±2 CE+PE | 100 | – | 100 | 0.2–2/s each |
| S2 FEED-2 | 2 the rest (~58) | cash + near futures | 116 | – | 116 | 1–5/s each |
| | promoted (≤ 5) | options ATM±2 + futures depth | ≤ 50 | ≤ 5 | ≤ 55 | |
| | | **Total** | | | **≈ 300–360** | **≈ 600–2,300 msgs/s at the open [HYPOTHESIS]** |

VIX by REST 1/min (a WS subscription to `INDVIX` is a probe item). Token lists are built from the scrip master at preflight and sent as `join` lists (the SDK does exactly this); FEED never calls `get_names` at 09:14.

**Error strings / subscription truth.** Our client has no string-returning path; the SDK requests no acknowledgement for a `join` and handles none [FACT], and what the server does with a bad token is unknown until the probe. The only truth about a subscription is therefore **the first tick**: every liquid row (hero, futures, cash) must tick within 120 s of 09:15 or of its join; otherwise "SUBSCRIBED BUT SILENT: <symbol> <token>" is alarmed and the token re-validated. Multi-token strings (the HDFCBANK `"1333 1469 17320"` corruption) are rejected at preflight.

**Session death** does not raise. Detection, fastest first: (1) socket.io `44` CONNECT_ERROR or an engine.io close on reconnect — seconds; (2) the 5-minute session probe (`get_customer_details`) returns a session error — ≤ 5 min; (3) a join after which a liquid instrument never ticks — 120 s. Alarm: **"SESSION DEAD — you cannot exit via API"** (audio, toast, red banner) with the EXECUTOR's state (flat / contract, qty) so the owner can act in the broker app. The fix is a token re-paste; the SUPERVISOR re-reads the store, FEEDs reconnect, REST re-authenticates — no restart.

**Reconnect:** backoff 2/4/8/16/30 s, **unlimited during market hours** (MYTHOS burned its 30 attempts before 09:15 and stayed dead all day — feed.py `reconnect_if_needed`), gated outside 09:00–15:35, re-join the full held list (held and hero tokens stay on it regardless of ATM drift).

**TLS trust — explicit and diagnosable.**
*What happened on 16 Oct.* **[FACT]** The staged `cert.pem` is **UTF-16LE with CRLF** (a PowerShell `>` redirect) containing **only the leaf** for `livestream.icicidirect.com` (issuer *GlobalSign GCC R46 EV TLS CA 2025*, valid **12 Oct 2026 11:06 UTC → 29 Apr 2027**, SHA-256 `20:6B:7D:64…24:AC`). OpenSSL cannot parse it, no env var referenced it, and a lone leaf would not satisfy `websocket-client`'s context (no partial-chain flag). Saving the file fixed nothing. **[HYPOTHESIS, strong]** Python's WS trust is the Windows ROOT+CA store read by OpenSSL, which fetches no intermediates. If the server's chain after the 12 Oct re-issue omitted the new intermediate, Python failed ("unable to get local issuer certificate") while browsers, which fetch via AIA, succeeded; *viewing* the certificate in Windows' viewer made CryptoAPI download and cache the intermediate in the Intermediate CA store — which `load_default_certs` read on the next attempt, one minute later. Alternative: ICICI fixed the server at ~11:10. Two checks settle it (§9).
*Design.* (1) Primary context `truststore.SSLContext` — verification by Windows CryptoAPI (`CertGetCertificateChain`, AIA on), i.e. what Edge/Chrome trust on that machine — injected into our client (and the SDK fallback via `websocket_extra_options`). (2) Fallback switch: certifi + a pinned UTF-8 PEM chain (`trust/icici_livestream_chain.pem`: leaf + intermediate + root), parse-checked at preflight. (3) Never `ssl_verify=False`. (4) `apex tls-probe <host>`: DNS → TCP (3 s) → TLS with verification (prints the exact `SSLCertVerificationError` reason) → TLS without verification to print the *served* chain (intermediate included?) → WebSocket upgrade to `/socket.io/?EIO=4&transport=websocket` → engine.io OPEN packet → verdict in < 5 s: `DNS_FAIL | TCP_REFUSED | TLS_VERIFY_FAIL(reason, served_chain_complete) | TLS_OK_NO_ENGINEIO | AUTH_REJECTED(44) | OK`; runs at preflight and on every connect failure; one line on screen. (5) Expiry countdown from the served leaf: amber 14 days before `notAfter` (the current leaf expires 29 Apr 2027; the next re-issue will try to repeat 16 Oct).

Order notifications are a separate socket to `livefeeds.icicidirect.com` [FACT]; the EXECUTOR owns it with the same TLS treatment.

### 5.6 REST scheduler (100/min, 5,000/day)

Priority: **P0** place/modify/cancel/square-off · **P1** positions, funds, order detail, session probe, limit calculator · **P2** Nifty chain · **P3** VIX · **P4** sister chains · **P5** Tier-1 stock chains · **P6** promotions, fallback quotes. Two lanes — order lane (P0–P1) and data lane (P2–P6) — on separate threads and `Session`s; the token bucket is the only shared gate: the data lane may use at most 60 of any rolling minute, so 40 are always free for orders; the day budget holds a hard reserve of 300 for P0–P1. Every call, retries included, writes a ledger row (`ts, lane, class, endpoint, status, latency_ms, day_count_after`) to SQLite (WAL); the budget reads the ledger at startup. The "day" is assumed to be the IST calendar day [HYPOTHESIS].

| Endpoint | Purpose | Cadence | Calls/day |
|---|---|---|---|
| customer details (session probe) | session alive | preflight + every 5 min | 76 |
| funds | capital | preflight + every 15 min + after fills | 41 |
| portfolio positions | reconciliation | preflight + every 5 min + after fills | 91 |
| order list/detail | reconcile when notifications are silent | ≤ 30 | 30 |
| place / modify / cancel / square-off | ≤ 15 trades × ~6 | | 90 (+300 reserve) |
| limit price & qty calculator | sizing per entry | | 15 |
| spot/sister bootstrap quotes | prev close, codes | preflight | 4 |
| INDVIX quote | VIX | 1/min | 375 |
| fallback quotes when a WS row is stale | | budgeted | ≤ 100 |
| NIFTY weekly chain CE+PE | wide OI, walls, GEX | every 90 s | 500 |
| NIFTY next-week chain CE+PE | rollover | every 10 min | 76 |
| BANKNIFTY/FINNIFTY chains CE+PE | positioning | every 5 min, round-robin | 300 |
| Tier-1 stock chains (10) CE+PE | walls, positioning | every 10 min | 750 |
| Tier-2 promotion chains | on promotion | ≤ 50 × 2 | 100 |
| preflight extras | | | 20 |
| **Total** | | | **≈ 2,570 + 400 reserve ≈ 59% of 5,000; steady ≈ 7/min** |

**Exhaustion ladder** on *projected* end-of-day use (burn rate × minutes left): L1 > 4,000 → stock chains every 20 min; L2 > 4,500 → sisters off, Nifty chain 3 min, VIX 5 min; L3 used > 4,600 → data lane only Nifty chain 10 min; L4 used > 4,800 → data lane closed, order lane only (≈ 30 trades left). Each step is an audible event; the gauge is always on screen.

### 5.7 The display contract
- **Per tick** for class 'H' (the Nifty complex): hero thread `sub.recv()` → `ws.send()` to each hero client; ticks arriving mid-send batch into the next TICK frame. **Coalesced** for everything else every 50 ms: rows whose `seq` changed (seqlock-checked table read), changed metrics, events.
- **Browser state:** mirror `ArrayBuffer` + schema-generated accessors, `Uint32Array` dirty bitmap, metrics mirror, event ring. Applying a TICK is `mirror.set(bytes, id*256)`.
- **Rendering:** rAF loop; **force ladder** (ATM±2, CE left / PE right: signed force bars, standing-order sparklines, vol/s, CVD, OI-Δ from the metrics mirror) on one canvas with per-row dirty flags; **futures book** canvas; **basket board** canvas ≤ 10 Hz; **event tape** DOM (append, cap 200; audio on state changes only — [OWNER]: commentary only for significant events, audible alerts). Age colouring at paint: fresh < 2 s, aging 2–10 s, stale beyond the row's class threshold → grey; a stale value is never used for an entry (§8).
- **Three stamps and the meter.** Per painted hero tick: `t_recv` (row), `t_gw` (frame), `t_arrive` (`performance.timeOrigin + performance.now()` in `onmessage`), `t_paint` (rAF timestamp + origin). Rolling-5-s p50/p99 of FEED→GW, GW→browser, browser→paint, plus the worst row's age; "EXCH→FEED ≈ 0–1 s" from `recv_ns − ltt_s`, honest about its 1-second resolution [FACT]. A 1-Hz ping proves the GATEWAY/browser clock offset is ~0.
- **The SLO:** hero feed-receive→paint **p50 ≤ 10 ms, p99 ≤ 30 ms, max ≤ 100 ms** over every rolling 10 s, 09:15–15:30, at 60 Hz (tighter at 120/144 Hz); basket ≤ 150 ms; GATEWAY→browser ≤ 2 ms p99. **Alarms:** amber p99 > 50 ms for 10 s; red (audio + toast) p99 > 100 ms, or any hero row older than 2 s in market hours, or no TICK frame for 1 s while FEED-0 reports ticks. `longtask` > 50 ms logged with attribution.
- **Background tab:** rAF pauses [FACT, MDN]; `onmessage` continues so nothing is lost; the page sends `{hidden:true}` → hero downgraded to coalesced 100 ms, meter suspended (no false alarm); on `visible` → SNAPSHOT, per-tick resumes within one frame. The SUPERVISOR sounds alarms regardless of the tab.

### 5.8 Watchdogs — MYTHOS failure modes mapped to detectors

| # | Inherited failure | Detector | Threshold / action |
|---|---|---|---|
| 1 | Spot tick loss while the process looked alive (06-15) | per-row silence vs the row's own p99 inter-arrival (floors: hero 2 s, futures/cash 15 s, far options 60 s) | amber 3×, red 10× or 30 s; resubscribe; P6 fallback quote for hero rows |
| 2 | Option feed stalled while spot ticked | composite "hero set alive" (10 hero rows + futures within 2 s) | red + audio; new entries blocked while red |
| 3 | HDFCBANK dead all day (multi-token) | first-tick watchdog; token validation at preflight | "SUBSCRIBED BUT SILENT" at 120 s |
| 4 | Session dead, subscribe returns strings | §5.5 three-stage detector | "SESSION DEAD — you cannot exit via API"; re-paste flow |
| 5 | REST chain silently frozen 3 h (07-06) | response signature (row count, ΣOI, max `ltt`) unchanged 3 polls; WS OI vs REST OI at ATM diverging > 5 min | "CHAIN FROZEN n min"; chain-derived metrics greyed |
| 6 | Reconnect budget burned pre-open | market-hours gate; unlimited attempts in hours | "reconnecting, next in n s" on screen |
| 7 | Orphaned socket on restart | Job Object; `41` + close on every exit path; slot-held backoff | hold time from the probe |
| 8 | NaN wedged the dashboard (06-15) | binary fixed-size frames; NaN = "no data" | cannot occur; length-checked |
| 9 | Dead daemon thread, process lives on | heartbeats in the control block | restart at 2 s; age per process shown |
| 10 | Stale cached `app.js` | schema carries a code hash | page reloads on mismatch |
| 11 | VIX ×100 glitch | range 5–90 with ×100 correction flag | last-good with age |
| 12 | Sister index dark all day; FinNifty code unknown | preflight quote validation; first-tick | "FINNIFTY ABSENT" badge, never silence |
| 13 | `%b` locale expiry; holiday-moved expiry | explicit English months; preflight prints the expiry and its chain row count (Mon 19 Oct this week [FACT]) | NO-GO on an empty chain |
| 14 | Analytics pass starving exits | exits read the table directly; `recv_ns` age gate | "STALE QUOTE → no decision" badge |
| 15 | Store queue drops on a slow disk | RECORDER drop counter; disk free ≥ 3× expected day at preflight and 12:00; Defender exclusion for `data/` | amber/red |
| 16 | Clock skew (REST checksum timestamp; meter meaningless) | preflight compares the local clock to the API's HTTP `Date` | NO-GO if > 1 s |
| 17 | TLS (16 Oct) | §5.5 probe; expiry countdown | verdict in < 5 s |
| 18 | Broker-side queueing on one socket (looks live, is late) | Nifty-futures canary across S0/S1; `recv_ns − ltt_s` creeping > 2 s; backlog flag (`recv()` returning with no wait 100× running) | "BROKER LAG n s" red; swap hero socket |

Automatic actions are limited to resubscribe, reconnect, restart, downgrade cadence and *block new entries*; this layer never places or cancels an order (G6). Every alarm is an 'E' event with an audio class, recorded.

### 5.9 Preflight (GO / NO-GO) and the morning
Checks in order, PASS/WARN/FAIL with the exact reason, ≈ 12 REST calls, token masked: (0) local — port free, no stale `apex` processes, disk space, `time.get_clock_info` precise, Python 3.13, pinned packages, no key-shaped strings anywhere in the tree; (1) TLS probe for `livestream`, `livefeeds`, `api`; (2) session; (3) clock skew vs API `Date`; (4) NIFTY spot + prev close; (5) VIX; (6) the computed weekly expiry and its chain row count, both rights; (7) constituent list → tokens from the scrip master, multi-token rejection, count vs expected; (8) sister codes; (9) funds and positions (flat unless the owner says otherwise); (10) one real socket: connect, join NIFTY spot + one option, first tick within 10 s if after 09:07, `41` + close; (11) today's ledger count. GO prints the subscription plan and the budget plan; intra-day the same checklist is live badges.

### 5.10 Build sequence and acceptance

| Step | Builds | Acceptance test |
|---|---|---|
| 0 | Schema (row, control block, metrics), `instruments.json` builder, `clk`, logging/`-X utf8` conventions | rows packed in Python decode bit-identically in the browser accessors |
| 1 | FEED against a synthetic socket.io server; RECORDER | **10k msgs/s for 10 min: hot-path p99 < 50 µs (parse→publish), < 100 µs including `recv`; zero RECORDER drops; per-instrument `seq` strictly increasing; < 30% of one core** |
| 2 | GATEWAY + page shell + meter | synthetic 2k msgs/s with 100 hero ticks/s: **feed→paint p99 < 30 ms for 30 min at 60 Hz**; background-tab resume ≤ 1 frame; kill GATEWAY → page resyncs ≤ 2 s |
| 3 | Raw Breeze client + probe harness + TLS probe | the capacity probe report (§6.1), every measurement present; A/B vs SDK path |
| 4 | MYTHOS frame converter + REPLAY-FEED (lockstep + timed) | two lockstep runs of 2026-07-02 hash identical; 60× timed replay paints smoothly |
| 5 | REST scheduler + ledger + pollers + session probe | simulated day ≤ 60% budget; ledger survives restart; ladder fires under injection |
| 6 | SUPERVISOR + watchdogs + preflight + alarms | fault matrix (§6.5): each fault → specified alarm within specified time → specified recovery |
| 7 | EXECUTOR plumbing with G6 (order lane, notification socket, timing) | place→ack→notification latency distribution on a shadow day; dead-session drill |
| 8 | Full shadow day (no orders); then G1–G4 workers plug in | flight report meets the SLOs; silent-instrument count 0 |

## 6. Validation plan

**6.1 First-day capacity probe** (Mon 19 Oct is expiry day; prefer Wed 21 Oct unless the owner wants expiry-day data). A standalone program logging raw messages, in stages: **A 09:12** S0 only (62 feeds, hero depth); **B 09:25** + S1; **C 09:40** + S2; **D 10:00** open a *fourth* socket with the same auth while the others run (two-sockets-per-session acceptance; does an existing socket drop?); **E 10:10** SDK-path socket beside the raw client on the 10 hero tokens for 10 min (A/B); **F 10:30** `leave` 50 tokens, time when ticks stop; **G 15:25** kill one socket's process uncleanly and time how long Breeze refuses a reconnect (slot hold). Measured: msgs/s per socket in 1-s bins (peaks 09:15 and 15:29); message size by type; inter-arrival per instrument; `recv()`→publish µs histogram; raw-vs-SDK per-tick cost and `ttq` regressions; `recv − ltt` skew (is `ltt` whole seconds?); fraction of NFO ticks carrying `OI`/`CHNGOI`; non-zero `NoOfOrders` in NFO depth; depth rate per hero contract; INDVIX on WS; a 200-token `join` list honoured in one emit; `pingInterval/pingTimeout` from the OPEN packet; slot-hold seconds. Output `probe_report.md` — the numbers that decide socket count, tier membership and recorder format.

**6.2 Synthetic load test.** A local socket.io-compatible server replays a recorded or converted day at k× with injected bursts (5k msgs in 100 ms) over three sockets; assertions as in step 1, plus GATEWAY hero p99 and zero RECORDER drops at 10k msgs/s for 10 min, and worker drop counters visibly counting.

**6.3 Latency acceptance (live).** First shadow day, 09:15–09:45: feed→paint p50 ≤ 10 ms, p99 ≤ 30 ms from the meter's own log; GATEWAY→browser ≤ 2 ms p99; no `longtask` > 100 ms; basket ≤ 150 ms; deliberately fat 40-KB coalesced frames must not move the hero p99.

**6.4 Replay determinism.** Lockstep replay of one log twice → identical SHA-256 of the metrics/event stream; 10× vs 100× → identical (speed-invariance); a converted MYTHOS day (`low_res_source`) replays end-to-end with depth-dependent metrics NaN and everything else live.

**6.5 Fault-injection matrix.** Kill each process · network cut 20 s · dead session token · corrupted token · frozen REST chain (stub) · garbage tick · browser closed 2 min · disk full · clock skew +3 s · `44` CONNECT_ERROR · 5-s TLS handshake · protocol shape change (len-24 array). Each row asserts alarm text, channel, detection time, automatic action, operator action.

## 7. Risks and failure modes — especially the silent ones

1. **Late-but-live display:** broker-side queueing shows moving prices that are seconds old; only the canary and the `recv − ltt` skew see it, and `ltt` is 1-s coarse [FACT] — sub-second broker lag is invisible and the meter says so.
2. **Reordering on the SDK path** silently regresses a row to an older tick [FACT] → raw client + monotonic guard.
3. **Socket capacity at ~300 feeds is unknown** [FACT, brief] → degrade by tier (stock options first, then Tier-2 futures); the hero socket is light by construction.
4. **Two sockets per session may be refused** → single socket, hero tokens joined first; probe stage D decides.
5. **ICICI protocol change** → shape canary + SDK fallback flag (minutes, not a day).
6. **TLS re-issue** (next ≈ April 2027) → `truststore` + probe + countdown.
7. **Browser/OS jank** (Chrome Energy Saver, Windows power plan, Defender scanning `data/`, a heavy second tab) → runbook items; `longtask` makes them visible.
8. **GATEWAY fan-out stall** from a slow second browser → per-client drop-oldest queues; the hero thread never blocks.
9. **REST exhaustion by a retry bug** → ledger-charged retries, the ladder, the gauge.
10. **The 5,000/day window definition** [HYPOTHESIS] → the ledger keeps calendar and rolling views; the stricter gates.
11. **Shared-table lifetime**: the block is freed when the last handle closes; children hold handles; the tree dies together.
12. **Replay fidelity**: converted MYTHOS frames lose intra-frame order and depth — good for domino/synchrony hypotheses at 1–2 s and for plumbing, wrong for force thresholds; the `low_res_source` flag prevents calibrating on them.
13. **Credentials**: the old test scripts carried keys in plaintext; preflight refuses GO if key-shaped strings exist in the tree.

## 8. Interfaces

**To G1–G4.** (a) `apex.table.Reader`: `row(id)` (seqlock-checked copy), `rows(ids)`, `age_s(id)`, `metric(id, m)`; `instruments.json` (id, class, symbol, exchange, product, expiry, strike, right, token, lot, tick size, index weights); `metrics.json` (register names; 64 slots per instrument, extendable). (b) `apex.stream.Sub(classes, hwm)`: every tick in socket order as `(id, row)`; drops counted and visible; consume in ≤ 20 µs or buffer. (c) `apex.clk.now_ns()` — virtual in replay, precise wall live; never `time.time()` for market logic. (d) Rules: never write instrument rows; stamp every output; a value older than its horizon is invalid and greyed (brief §5.5); volume from `ttq` differences, never `ltq`; book changes timed by `recv_ns`, trades by `ltt_s`; `low_res_source` rows carry no depth.

**From G6.** (1) The order-path latency they need from trigger to `place_order` return and to the first notification, and whether they accept the REST process's order lane or want their own process (the budget object is shared either way). (2) Their consumption of the `livefeeds` notification socket — we provide the client, TLS probe and reconnect; they parse messageType 4–7 [FACT, SDK `parse_data`]. (3) The position row they want in the table (contract id, qty, avg, open order id/status, last notification time). (4) The kill-switch contract: SUPERVISOR → "block new entries" (ours) vs "flatten" (theirs only). (5) Behaviour in a position when FEED-0 dies: table age + P1 fallback quotes on the order lane. (6) The replay fill model (fills from recorded depth at virtual time). (7) The order-lane reserve they want (we hold 300/day, 40/min).

## 9. Open questions for the owner

1. On 16 Oct, how did you "save" the certificate — browser certificate viewer, `certmgr`? Please check: `certmgr.msc → Intermediate Certification Authorities` — is **GlobalSign GCC R46 EV TLS CA 2025** there, and dated when? And from the Windows box: `openssl s_client -connect livestream.icicidirect.com:443 -servername livestream.icicidirect.com -showcerts` — one certificate or two? (Plus `python -c "import ssl,sys;print(sys.version, ssl.OPENSSL_VERSION)"`.)
2. May the probe open a second socket on the live session (stage D), accepting that a refusal could drop the running socket on that shadow day? Which day — Mon 19 Oct (expiry) or Wed 21 Oct?
3. Browser (Chrome/Edge), monitor refresh rate, single or dual monitor — the SLO scales with frame time.
4. Retention: how many days of full-tick logs (≈ 1–2.5 GB/day compressed)?
5. Does ICICI's 5,000/day window reset at midnight IST or roll 24 h?
6. SUPERVISOR audio + Windows toast as the primary alarm channel, browser secondary — acceptable?

## 10. Summary for the master design

G5 proposes a process-isolated tick path for Windows/Python 3.13: one FEED process per Breeze socket (three), each running our own minimal socket.io client over `websocket-client` — the SDK's path spawns a thread per tick, reorders ticks, hides connect errors and truncates exchange time to whole seconds, all verified in source — parsing with orjson into a fixed 256-byte instrument row that lives in a seqlocked shared-memory table and is republished unchanged on ZeroMQ, appended unchanged by the RECORDER to a sequenced per-socket log, and forwarded unchanged by a compute-free GATEWAY over two binary WebSockets to a browser that mirrors the table in typed arrays and paints on canvas at the refresh rate. Measured hot-path cost is ≈ 12–18 µs per tick against a 50 µs budget that is itself a dashboard number. "No delay" is feed-receive→paint p50 ≤ 10 ms / p99 ≤ 30 ms with alarms; staleness is per-value age with watchdogs for every silent failure MYTHOS suffered; TLS trust is explicit and diagnosable in five seconds; REST is a persisted two-lane ledger at ≈ 59% of the daily budget; and replay drives the entire system deterministically from a recorded day — or, flagged low-resolution, from the 8.2 GB of MYTHOS frames on day one.

---

*Sources read this session:* `breeze_connect` 1.0.69 (`breeze_connect.py`, `config.py`, PyPI sdist); `python-engineio` 4.14.0 `client.py`; `python-socketio` 5.17.0 `client.py`; `websocket-client` 1.9.2 `_http.py`; `pyzmq` 27.2.0 `zmq/asyncio.py`; `websockets` 17.2 `sync/server.py`; `truststore` `_windows.py`; Python docs — `ssl` (`load_default_certs`, `enum_certificates`, 3.13 default verify flags), `time` (Windows clocks, 3.13 changes), `multiprocessing.shared_memory` (Windows lifetime); libzmq docs — `zmq_ipc`, `zmq_setsockopt` (`ZMQ_CONFLATE`, HWM, `ZMQ_XPUB_NODROP`); MDN `requestAnimationFrame`; the staged MYTHOS/HAWK files named in the charter; `cert.pem` from the staged tree (metadata only — no key material exists in it). Micro-benchmarks ran in this container (Linux, Python 3.13.16) and are indicative until re-run on the owner's machine.
