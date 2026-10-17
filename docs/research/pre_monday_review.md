# ApexOptions — pre-Monday (19 Oct 2026, 0DTE) bug hunt

Scope: every file under `apex/`, `run_apex.py`, `tests/`, `apex/static/app.js`, checked against
`breeze_connect 1.0.69` (`SocketEventBreeze`, `get_stock_token_value`, `subscribe_feeds`,
`ws_disconnect`, `generate_session`, `get_names`) and `python-socketio 5.17 / python-engineio 4.14`
(the versions `pip install breeze-connect` pulls today). Claims below were verified by reading the
code paths and, where possible, by running them: `tests/test_core.py` passes on Python 3.13 /
numpy 2.5; a harness drove the engine through a full synthetic 19-Oct session (09:15 empty table →
spot only → futures only → full book → forced entries → 13:00 next-week switch → 15:00 0DTE
flatten → 15:25 flatten → 15:31 learn) without an exception; the SDK's `get_stock_token_value`
was executed on a stub master to confirm its failure return value.

Counts: **BLOCKER 0 · HIGH 4 · MEDIUM 9 · LOW 8**. Nothing found that deterministically crashes
or stops trading at 09:15 on the happy path; the HIGHs are silent wrong-number / wrong-instrument
conditions that are triggered by things that are likely on a first live day (starting before the
open, a feed restart, a 30-second silence).

---

## HIGH

### H1. Feed-level reconnect never tears down the old socket.io client → duplicate clients, duplicate packets, a reconnect storm if started before ~09:08
`apex/feed_breeze.py:305-314` (`reconnect`), `:377-382` (silence rule from **09:00**), SDK `breeze_connect.py:90-91, 213-220`.

- `BreezeFeed.reconnect()` calls `breeze.ws_disconnect()`. In the SDK that is `on_disconnect()` →
  `self.sio.emit("disconnect", "transport close")` — it **emits an event named "disconnect" to the
  server**; it never calls `sio.disconnect()`. Then it sets `sio_rate_refresh_handler = None` and
  `connect()` → `ws_connect()` builds a **new** `SocketEventBreeze`/`socketio.Client`. The old
  `Client` object stays alive in its own threads (engineio read loop, auto-reconnect task), still
  subscribed (its `rewatch` re-joins `tokenlist` on every `connect` event, python-socketio
  `reconnection=True` by default) and still calling our patched class-level `on_message`.
  Result after every feed-level reconnect: N clients all delivering the same stream; `msgs`,
  `ticks`, recorder lines and the thread-per-message load multiply by N (engineio dispatches every
  message on a fresh thread: `engineio/client.py:436, 141-156`).
- If `emit` raises (`BadNamespaceError` when the client is mid-reconnect), the `except` in
  `reconnect()` swallows it and `sio_rate_refresh_handler` is **not** reset, so the next
  `ws_connect()` calls `sio.connect()` on a client that is already reconnecting; both paths race.
- Trigger on Monday: `in_mkt` starts at **09:00** but NFO has no pre-open and index/cash
  pre-open packets are sparse until ~09:08; starting `live` after preflight (README: before the
  open) gives up to ~16 silence-driven reconnects before 09:15 → up to 16 duplicate clients on the
  09:15 burst. Also fires all day on a holiday (no `is_trading_day` check).
- Fix (minimal):
  ```python
  def reconnect(self):
      self.t.set("feed_state", 3); self.t.set("reconnects", int(self.t.c("reconnects")) + 1)
      h = getattr(self.breeze, "sio_rate_refresh_handler", None)
      if h is not None:
          try: h.sio.reconnection = False; h.sio.disconnect()      # real teardown, no auto-reconnect
          except Exception: pass
      self.breeze.sio_rate_refresh_handler = None
      time.sleep(1); return self.connect()
  ```
  and `in_mkt = config.is_trading_day(now.date()) and mins((9,15)) <= hm(now) <= mins((15,35))`.
  (Optional: leave the SDK's own auto-reconnect to do its job and lengthen the silence threshold.)

### H2. A feed restart mid-session silently corrupts the engine's view: registry version restarts at 1 and the table's `ttq` guard blocks new instruments
`apex/feed_core.py:50, 78-86` (`Registry.version` starts at 0), `apex/engine_main.py:76-79`
(`if v == self.reg_version: return`), `apex/feed_core.py:139-141` (ttq monotonic guard),
`run_apex.py` supervisor restarts the live feed on any exit; `apex/engine/paper.py:164` (`by_id[pos["id"]]`).

- The supervisor restarts the feed whenever it exits (SystemExit from `build()`, PermissionError
  from `os.replace` on Windows while the gateway is reading `instruments.json`, any uncaught
  error). The new `BreezeFeed` builds a fresh `Registry` whose first `save()` writes
  `reg_version = 1`. The engine already has `reg_version == 1` (no re-centre yet) → **it never
  reloads** and keeps the old id→instrument map. The new build orders options around the
  *current* spot (`band_center` from `rest_spot()`), so if spot moved ≥ 25 pts every option id
  now points at a different strike: Greeks, hero ladder, `choose_contract`, the open position's
  LTP (`by_id[pos["id"]]`) and its P&L are all computed on the wrong contract.
- Independently, the shared table is not cleared on restart (only the supervisor zeroes it). The
  guard `ttq_new < old_ttq → drop` then rejects **every** quote for an instrument whose new row id
  previously held a higher cumulative volume (e.g. an option landing on a row that held a stock) —
  that instrument is dead for the rest of the day.
- Fix: (a) in `BreezeFeed.__init__`: `self.reg.version = int(table.c("reg_version"))` (continue the
  sequence) and `table.rows[:] = 0` (the feed is the sole row writer); (b) in the engine, key the
  position lookup by `key`, not `id` (`ctx["by_key"] = {o["key"]: o ...}`; `check_exit` uses
  `ctx["by_key"].get(pos["key"])`), and reset `Market`/`Flow` history on a registry change whose
  ids moved; (c) wrap `os.replace` in `Registry.save`/`write_chain` in a 5× retry on
  `PermissionError` (Windows cannot replace a file another process has open).

### H3. Futures impulse scale: the 4-pt seed is discarded on the first sample and pre-open zeros dilute σ15 → z inflated 1.5–2.5× for the first hour
`apex/engine/domino.py:29-34` (`EW.add`: `a = max(1/n, …)` → with n=1, a=1 → `v = x`),
`:73-83` (`r15 = 0.0` when the price is NaN, then `fut_sigma.add(abs(r15))` every second).

- `EW.add` with `n == 1` overwrites the seed with the first sample, so `SIGMA15_SEED = 4.0` is
  never used ("used until the 20-min scale warms up" is false). Before 09:15 the futures row is
  NaN → `r15` is forced to `0.0` → zeros are fed to the EWMA at 1 Hz. With half-life 1200 s and
  the `max(1/n, α)` fast-start, the EWMA is a plain running mean for the first ~29 minutes: start
  at 09:00 → at 09:25 σ15 ≈ 0.4 × the true value → `z = r15/σ` is 2.5× too large → `m_star = 2`
  is crossed by moves that are really ~0.8σ; `lateness` (`L_star·σ`) is also 2.5× too strict.
  Direct effect on the first trades of the day (the owner's paper record).
- Fix: in `Domino.update` only feed `fut_sigma` when `np.isfinite(m.change(m.ltp,15)[fut_id])` and
  `hm(now) >= 09:15`; in `EW.add` use `a = max(1.0/(self.n + 1), α)` so the seed counts as one
  observation (or start `n = 1` when a seed is given).

### H4. `get_stock_token_value` does not fail on an unknown contract — it returns `('4.1!False', '4.2!False')`, and `BreezeFeed.token()` accepts it
`apex/feed_breeze.py:128-140`; SDK `breeze_connect.py:310-379` (`subscribe_exception` *returns*
an Exception, nothing raises; verified by execution: unknown NFO contract → `('4.1!False','4.2!False')`,
unknown NSE code → `('4.1!False', False)`).

- Consequences: every "try candidates until one resolves" loop in `build()` is dead code — the
  first ISEC hint / index code / monthly-expiry candidate always "wins" (`isec()`, the
  BANKNIFTY/FINNIFTY loop, the Thursday fallback for stock futures) and a wrong one is cached in
  `token_cache.json` for good. Unknown strikes become instruments with token `4.1!False` (all of
  them share `by_token["fo"]["False"]`), `depth=True`, and get subscribed. No log line is
  produced; the instrument is simply silent. On Monday the verified names (NIFTY, hinted ISEC
  codes, 19-Oct/27-Oct expiries) should resolve, but anything that doesn't (a non-hinted stock,
  a next-week strike not yet listed, a stock future on a Thursday expiry) disappears without a trace,
  and after 27 Oct the cached stock-future expiry is stale and will "resolve" to `False` forever.
- Fix: in `token()`: `if isinstance(r, tuple) and r[0] and "False" not in str(r[0]): return r[0], (r[1] if r[1] and "False" not in str(r[1]) else None)`;
  log every unresolved contract; in `build()` ignore `cache["fut_exp"]` when it is `< today`;
  add a preflight check that resolves `NIFTY` (NSE), `NIFTY FUT 27-Oct-2026` and the ATM weekly
  CE/PE and asserts the tokens are numeric.

---

## MEDIUM

### M1. Ctrl+C: engineio re-installs a SIGINT handler in the feed; the feed dies with KeyboardInterrupt instead of running `shutdown()` → recorder tail lost, gzip left without end-of-stream marker
`apex/feed_breeze.py:423` (`SIG_IGN`), `engineio/base_client.py:12-24, 45-49` (`socketio.Client()` is
created on the feed's main thread inside `SocketEventBreeze.__init__`; `handle_sigint=True` by
default; the saved "original" handler `SIG_IGN` is not callable → `signal.default_int_handler` →
`KeyboardInterrupt`). `main()` catches only `SystemExit`/`Exception`, so the process exits with a
traceback, `Recorder.stop()` never runs (daemon writer thread killed → last ≤1 s of packets lost
and the `.jsonl.gz` has no trailer). `feed_replay.run()` then raises `EOFError` at the end of the
file (the `try` only wraps `json.loads`), the replay feed exits without setting `feed_state=7`, the
engine never finishes and the supervisor hangs until Ctrl+C.
Fix: in `BreezeFeed.run()` wrap the main loop in `try/except KeyboardInterrupt: pass` before
`self.shutdown()` (or re-set `signal.signal(SIGINT, SIG_IGN)` after the first `ws_connect()`);
in `feed_replay.run()` catch `(EOFError, OSError)` around the read loop and still set `feed_state=7`.

### M2. Spot never used as a fallback for the basket conversion → synchrony is 0 all day if the NIFTY spot row never ticks
`apex/engine/domino.py:85, 105` (`N = self.price(m, self.spot) if self.spot is not None else …`).
If `NIFTY|SPOT` resolves (H4 makes a bogus token look resolved) but never ticks, `N` is NaN,
`_moves` returns all-NaN, `S_up = S_dn = 0` → `synchrony 0.00 < 0.5` forever; the engine itself
happily falls back to futures for price. Fix: `N = spot if finite else fut`.

### M3. Preflight can say GO when the websocket cannot connect or tokens do not resolve
`run_apex.py:cmd_preflight`. It validates REST (`generate_session`) and a raw TLS handshake to
`livestream.icicidirect.com`, but not the socket.io connect/auth (the 16-Oct failure mode), nor
token resolution, nor the NIFTY REST quote that `build()` depends on. Add: `ws_connect()` +
`ws_disconnect()` round-trip, resolve the four tokens from H4, `get_quotes(NIFTY, NSE, cash)` returns
ltp or previous_close. False FAIL risks are small (port busy / truststore missing are real failures).

### M4. `end_day()` runs again if the engine is restarted after 15:31
`apex/engine_main.py:113-125, 143-144`. `_learned` lives on the instance; a restart re-runs
`learning.learn()` for the same day: `s["log"]` gets duplicate entries, `retired` can get the same
champion twice, `champion_since` can be reset. `record_day` is idempotent. Fix: persist a
`learned_day` marker in `state.json` (or check `s["log"][-1]["day"] == day`) before learning.

### M5. `Table.snapshot()` seqlock is only half implemented
`apex/table.py:125-131`. It re-reads rows whose seq was odd *in the copy*, but a row whose write
started and finished while the 200 KB memcpy was in flight has an even seq and torn fields
(e.g. new `ttq` with old `ltp`, which `Flow.update` classifies as aggressive volume). Rare at 10 Hz
but it is the only sample path. Fix: `s0 = rows["seq"].copy(); snap = rows.copy(); s1 = rows["seq"].copy();
bad = (s0 != s1) | (s1 & 1); re-read bad (loop until clean)`.

### M6. Dashboard: `pnlBuf` grows without bound while a position is open; `Math.max(1, ...pnlBuf.map())` will throw on a long hold and freeze `render()`
`apex/static/app.js:219, 254`. 4 Hz × a multi-hour hold (a trailing runner, or a 0DTE Δ≥0.9 hold
until 15:25) → tens of thousands of elements; V8 throws `RangeError: Maximum call stack size
exceeded` on a spread of ~100k+ args; the exception is inside `render()` so every state frame
aborts after `pnlBuf.push`, and the whole page stops updating until the position closes.
Fix: cap (`if (pnlBuf.length > 4000) pnlBuf.shift()`) and compute the max with a loop.

### M7. `Pressure._walls` marks every strike a wall when OI is all zero
`apex/engine/levels.py:81-88`: `q75 = 0`, `mean(nb) = 0`, `oi[j] >= 0` → every near strike is a
"wall" (a REST chain glitch, or next-week style sparse OI) → `room` advisor vetoes everything,
`Force.levels` is flooded with levels. Advisory only on day 1 (no gates), but it feeds the
learning data. Fix: require `oi[j] > 0`.

### M8. `choose_contract`: `ZERO_DTE_NO_ENTRY` (14:45) is a dead branch; design says "0DTE only at Δ≥0.8 after 13:00, none after 14:45"
`apex/engine/paper.py:75-81`: both the `>= 14:45` and `>= 13:00` branches do the same thing
(next-week only). The spec (D-021, OQ-8) allows a 0DTE Δ≥0.8 contract between 13:00 and 14:45;
the code never offers it, and keeps taking next-week entries until 15:15. Not a crash; confirm it
is the intended Monday behaviour (the harness shows next-week entries at 15:00-15:15 followed
by the 15:25 flatten).

### M9. `subscribe_feeds` returning `None` counts as success
`apex/feed_breeze.py:279-286`: when the SDK has no rate handler (`ws_connect` never succeeded,
or `ws_disconnect` ran), `subscribe_feeds` falls through and returns `None`; the feed then adds
the chunk to `self.subscribed` and logs "subscribed N streams (0 rejected)". `connect()` clears
the set first, so it self-heals on the next successful connect, but `maybe_recenter()` during an
outage silently "subscribes" nothing. Fix: treat `not isinstance(r, dict)` as rejected.

---

## LOW

- **L1** `apex/feed_breeze.py:264-266` `HotStats.add` is called from many SDK threads without the
  lock; `self.n`/`self.last` races only skew the µs stats (tested: `np.fromiter` over the deque
  does not raise under the GIL). Move it inside `with feed.lock` for clean numbers.
- **L2** `apex/feed_core.py` `Registry.add` on an existing key keeps the old `depth_token=None`:
  strikes that become heroes after a re-centre never get depth; the flow classes then use best-bid
  size only. Update `depth_token` when `depth` turns True and subscribe it.
- **L3** `apex/feed_breeze.py:229-230` cached `fut_exp` is used even when it is in the past
  (from 28 Oct every stock future silently resolves to `False`, see H4). Compare with today.
- **L4** `run_apex.py:supervise` on Windows, a zombie engine from a previous session (console
  closed without Ctrl+C, port already freed) makes `SharedMemory(create=True)` raise
  `FileExistsError` with no hint; print "another ApexOptions process still holds apex_table_v1".
- **L5** `run_apex.py:cmd_report/cmd_learn` print `report.md` (₹, Σ, →) from the parent process
  without `PYTHONIOENCODING`; fine on a real console (UTF-8), `UnicodeEncodeError` when redirected
  to a file. Add `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in `main()`.
- **L6** SDK REST calls (`requests.get` in `make_request`, `api_util`) have no timeout; a hung
  `rest_spot()` blocks feed start-up forever, a hung chain poll stalls VIX/chain. Set
  `requests.adapters.DEFAULT…` or monkeypatch `make_request` with `timeout=10`.
- **L7** `apex/static/app.js:43` `loadInstruments()` is fired on every tick message while
  `d.v !== REGV`; if `/api/instruments` ever returns `version: 0` (file unreadable) the browser
  issues ~250 fetches/s. Debounce with an in-flight flag.
- **L8** SDK import side effects to be aware of: `breeze_connect.py:26-31, 55-56` downloads
  `SecurityMaster.zip` at import **and** again in `generate_session`, creates `./logs/` in the CWD
  and logs every REST response at DEBUG to `logs/apiLogs.log` (grows ~50 MB/day with 90-s chain
  polls); `sys.path.insert(1, <sdk dir>)` puts a top-level `config` module on the path (no clash with
  `apex.config`, which is imported relatively).

---

## Checked and found OK (no action)
- Packet parsing vs SDK layouts; `kind`/`n` segment selection; depth packets; `ltt` kept numeric.
- The `on_message` monkeypatch: `watch()` binds `self.on_message` at subscribe time, after
  `hook()`; `rewatch` also picks up the patched method; signature `(sock_self, data)` matches.
- `subscribe_feeds(stock_token=[…50])`: list joins are what the SDK's own `rewatch` does; the
  "Exception while subscribing…" string is detected; the dict on success is ignored correctly.
- Engine live path at 09:15 with an empty table, spot-only, futures-only: no exception (harness).
  `compute_greeks` empty-slice warnings are suppressed by the `RuntimeWarning` filter.
- 0DTE paths: `years_to_expiry` 600-s floor, `zero_am` band before 13:00, next-week after 13:00,
  15:00 flatten unless Δ≥0.9 (ITM with invalid IV → Δ=±0.99 → held, as I-7 intends), 15:25
  flatten, `end_day` at 15:31 exactly once per process, calendar: w0 = 19 Oct, w1 = 27 Oct,
  futures 27 Oct (tests pass).
- Sizing `floor(capital/(ltp·65))`, stop/trail in futures points, THESIS-VOID, `fired_episodes`
  persistence, capital compounding, trades CSV, `learn()` with zero trades.
- State keys the dashboard reads all exist in `publish()` (`pos.stop_fut` appears from the second
  step; `fmt(undefined)` renders "—"); `render({})` before the engine starts does not throw.
- Shared memory: `track=False` with `TypeError` fallback for < 3.13; children attach by name; the
  supervisor zeroes `stop`; `StateBlob` seq protocol; JSON `clean()` handles numpy scalars/NaN.
- Resource growth over 6.25 h: all deques/rings bounded; `Recorder` queue bounded (1e6);
  `oi_hist` 400×~120 floats; `events` 120; browser `ages`/`futBuf`/`legs`/`beads` bounded
  (except `pnlBuf`, M6).
- `os.replace` ordering: readers open `instruments.json`/`chain_latest.json` only after the
  version bump, so a Windows sharing violation needs an unlucky `/api/instruments` request during a
  re-centre (then H2 applies).
