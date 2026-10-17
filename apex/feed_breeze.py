"""
FEED process — live ICICI Breeze data (paper trading; no orders are ever sent).

Runs as its own process so nothing that thinks shares its interpreter.
  * logs in with the day's session token (secrets/breeze[_<profile>].json)
  * resolves every contract to a stream token offline (SDK security master)
  * hooks the SDK's raw socket.io message handler so we receive the untouched
    packet array (numeric exchange time, no per-tick strftime/dict building)
  * writes each packet into the shared table and the recorder
  * polls VIX (60 s) and the Nifty weekly chain (90 s) on a REST budget
  * re-centres the option band as Nifty drifts, reconnects on silence

Run via:  python run_apex.py live   (the supervisor starts this module)
"""
import json
import os
import sys

import numpy as np
import threading
import time
import traceback
from datetime import datetime

from . import config, universe
from .feed_core import HotStats, Recorder, Registry, apply_packet, replace_retry
from .table import Table

LOG = None


def log(msg):
    line = f"{datetime.now(config.IST).strftime('%H:%M:%S')} FEED {msg}"
    print(line, flush=True)
    try:
        LOG.write(line + "\n"); LOG.flush()
    except Exception:
        pass


def load_credentials(profile: str = ""):
    name = f"breeze_{profile}.json" if profile else "breeze.json"
    path = os.path.join(config.SECRETS_DIR, name)
    if not os.path.exists(path):
        raise SystemExit(f"Missing {path}. Run:  python run_apex.py session"
                         + (f" --profile {profile}" if profile else ""))
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    for k in ("api_key", "api_secret", "session_token"):
        if not c.get(k):
            raise SystemExit(f"{path} lacks '{k}'. Run: python run_apex.py session")
    return c


def install_trust():
    """Trust the Windows certificate store (with intermediate fetching) for every
    TLS connection — the cure for the 16 Oct 'Failed to connect to live stream'.
    No-op if truststore isn't installed."""
    try:
        import truststore
        truststore.inject_into_ssl()
        return "truststore (Windows store)"
    except Exception:
        return "python default (install 'truststore' for Windows-store trust)"


# ── the tick socket, done by hand ──────────────────────────────────────────
# BreezeConnect.ws_connect() swallows every failure into one sentence, "Failed to
# connect to live stream", waits only 3 s for the server's CONNECT reply, and
# registers its connect_error handler AFTER connecting (so the server's reason is
# never heard).  These helpers do the same handshake the SDK does — same URL, same
# User-Agent, same auth dict, websocket-only transport — but keep the real error.
STREAM_HEADERS = {"User-Agent": "python-socketio[client]/socket"}
WS_CONNECT_WAIT_S = 15.0       # the SDK's 3 s is too short on a slow link / busy auth backend


def stream_versions():
    """Versions of the three libraries that make the socket, for the preflight line."""
    from importlib.metadata import version
    out = []
    for dist in ("python-socketio", "python-engineio", "websocket-client"):
        try:
            out.append(f"{dist} {version(dist)}")
        except Exception:
            out.append(f"{dist} missing")
    return ", ".join(out)


def stream_url(path="/socket.io/?EIO=4&transport=websocket"):
    from breeze_connect import config as bcfg
    base = bcfg.LIVE_STREAM_URL.rstrip("/")
    return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + path


def stream_probe(timeout=10.0):
    """Raw Engine.IO handshake with the livestream host — the first thing the SDK's
    socket does — returning (ok, detail).  A failure here is the real cause behind
    'Failed to connect to live stream': a 400 (protocol mismatch), 401/403 (refused),
    an SSL verification error (trust store), a proxy refusing CONNECT, or a timeout."""
    import websocket
    url = stream_url()
    try:
        ws = websocket.create_connection(url, header=dict(STREAM_HEADERS), timeout=timeout)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"
    try:
        ws.settimeout(timeout)
        first = ws.recv()
    except Exception as e:
        first = f"<no open packet: {type(e).__name__}: {str(e)[:80]}>"
    finally:
        try:
            ws.close()
        except Exception:
            pass
    s = first.decode(errors="replace") if isinstance(first, bytes) else str(first)
    if s.startswith("0{"):
        return True, "engine.io OPEN received" + (" (sid ok)" if '"sid"' in s else "")
    return False, f"unexpected first frame: {s[:120]}"


def stream_hint(detail):
    """One line of advice for a stream_probe / connect_stream failure text."""
    d = detail.lower()
    if "handshake status 400" in d:
        return "server rejected the Engine.IO handshake — protocol mismatch: pip install -U python-socketio python-engineio websocket-client"
    if "handshake status 401" in d or "handshake status 403" in d:
        return "server refused the socket (401/403) — blocked network, or the stream is closed right now"
    if "handshake status 5" in d:
        return "livestream server error (5xx) — ICICI side; retry later"
    if "certificate_verify_failed" in d or "sslcertverificationerror" in d or "sslerror" in d or "ssl:" in d:
        return "TLS trust: pip install truststore (uses the Windows certificate store)"
    if "proxy" in d:
        return "a proxy is in the way — websocket CONNECT through it is being refused"
    if "timed out" in d or "timeout" in d:
        return "no answer in time — firewall / VPN / ISP blocking websockets, or a very slow link"
    if "refused" in d or "10061" in d:
        return "port closed — connection refused by the host"
    if "getaddrinfo" in d or "name or service" in d or "nodename" in d:
        return "DNS failure for the livestream host"
    if "namespaces failed to connect" in d:
        return "the server answered but rejected the Socket.IO connect — usually the session token (regenerate it) or the stream is not open right now"
    if "unexpected connection error" in d:
        return "transport connected but the server never sent CONNECT within the wait — slow auth backend, or the stream is not serving right now"
    return ""


def connect_stream(breeze, wait_timeout=WS_CONNECT_WAIT_S):
    """Connect the SDK's tick socket ourselves and hand it back to the SDK
    (breeze.sio_rate_refresh_handler), so subscribe_feeds() keeps working.
    Raises RuntimeError with the real cause instead of the SDK's one-liner."""
    from breeze_connect import breeze_connect as bc, config as bcfg
    h = bc.SocketEventBreeze("/", breeze)
    reasons = []

    def _connect_error(data=None):          # registered BEFORE connecting — the SDK does it after
        h.authentication = False
        if data is not None:
            reasons.append(str(data)[:160])
    h.sio.on("connect_error", _connect_error)
    auth = {"user": breeze.user_id, "token": breeze.session_key}
    if not auth["user"] or not auth["token"]:
        raise RuntimeError("no user id / session key — generate_session() did not complete")
    try:
        h.sio.connect(bcfg.LIVE_STREAM_URL, headers=dict(STREAM_HEADERS), auth=auth,
                      transports="websocket", wait_timeout=wait_timeout)
    except Exception as e:
        try:
            h.sio.reconnection = False
            h.sio.disconnect()
        except Exception:
            pass
        why = f"{type(e).__name__}: {str(e)[:160]}"
        if reasons:
            why += f" — server said: {reasons[-1]}"
        raise RuntimeError(why) from None
    if not h.sio.connected:
        raise RuntimeError("handshake returned but the socket is not connected")
    h.authentication = True
    breeze.sio_rate_refresh_handler = h
    return h


def drop_stream(breeze):
    """Tear the SDK's tick socket down for real (its ws_disconnect only EMITS an event)."""
    h = getattr(breeze, "sio_rate_refresh_handler", None)
    if h is not None:
        try:
            h.sio.reconnection = False
            h.sio.disconnect()
        except Exception:
            pass
    breeze.sio_rate_refresh_handler = None


class RestLedger:
    """Counts every REST call per IST day, persisted, so restarts can't overspend."""

    def __init__(self, table):
        self.t = table
        self.path = os.path.join(config.DATA_DIR, "rest_ledger.json")
        self.day = config.now_ist().date().isoformat()
        self.n = 0
        self.minute = []
        try:
            d = json.load(open(self.path))
            if d.get("day") == self.day:
                self.n = int(d.get("n", 0))
        except Exception:
            pass
        self.lock = threading.Lock()

    def take(self, cap=config.REST_DAY_DATA_CAP) -> bool:
        with self.lock:
            now = time.time()
            self.minute = [t for t in self.minute if now - t < 60]
            if self.n >= cap or len(self.minute) >= 60:
                return False
            self.n += 1
            self.minute.append(now)
            self.t.set("rest_today", self.n)
            try:
                json.dump({"day": self.day, "n": self.n}, open(self.path, "w"))
            except Exception:
                pass
            return True


class BreezeFeed:
    def __init__(self, table: Table, profile: str = ""):
        self.t = table
        self.profile = profile
        self.reg = Registry()
        self.reg.version = int(table.c("reg_version"))      # a restart continues the sequence
        table.rows[:] = np.zeros(config.MAX_ROWS, dtype=table.rows.dtype)
        self.lock = threading.Lock()
        self.day = config.now_ist().date().isoformat()
        self.rec = Recorder(self.day)
        self.hot = HotStats(table)
        self.ledger = RestLedger(table)
        self.breeze = None
        self.subscribed = set()
        self.last_msg = time.monotonic()
        self.band_center = 0.0
        self.w0 = self.w1 = self.mexp = None
        self.cache = self._load_cache()

    # ── tokens ─────────────────────────────────────────────────────────────
    def _load_cache(self):
        try:
            return json.load(open(config.TOKEN_CACHE_JSON))
        except Exception:
            return {"isec": {}, "index": {}, "fut_exp": {}}

    def _save_cache(self):
        try:
            json.dump(self.cache, open(config.TOKEN_CACHE_JSON, "w"), indent=1)
        except Exception:
            pass

    def token(self, exch, code, product="", expiry="", strike="", right="", depth=False):
        """Return (quote_token, depth_token|None) or (None, None). Offline lookup."""
        try:
            self.breeze.interval = ""
            r = self.breeze.get_stock_token_value(
                exchange_code=exch, stock_code=code, product_type=product,
                expiry_date=expiry, strike_price=strike, right=right,
                get_exchange_quotes=True, get_market_depth=depth)
            if isinstance(r, tuple) and r[0] and "False" not in str(r[0]):
                d = r[1] if (r[1] and "False" not in str(r[1])) else None
                return r[0], d
        except Exception:
            pass
        log(f"unresolved: {exch} {code} {product} {expiry} {strike} {right}")
        return None, None

    def isec(self, sym):
        if sym in self.cache["isec"]:
            return self.cache["isec"][sym]
        hint = universe.ISEC_HINT.get(sym)
        cands = [hint] if hint else []
        try:   # offline: reads the SDK's security master, no REST call
            r = self.breeze.get_names(exchange_code="NSE", stock_code=sym)
            if isinstance(r, dict) and r.get("isec_stock_code"):
                cands.insert(0, r["isec_stock_code"])
        except Exception:
            pass
        for c in cands:
            q, _ = self.token("NSE", c)
            if q:
                self.cache["isec"][sym] = c
                self._save_cache()
                return c
        return None

    # ── session ────────────────────────────────────────────────────────────
    def login(self):
        import requests
        _orig = requests.Session.request
        def _req(self_, *a, **k):               # the SDK never sets a timeout
            k.setdefault("timeout", 15)
            return _orig(self_, *a, **k)
        requests.Session.request = _req
        from breeze_connect import BreezeConnect
        c = load_credentials(self.profile)
        self.breeze = BreezeConnect(api_key=c["api_key"])
        self.breeze.generate_session(api_secret=c["api_secret"], session_token=c["session_token"])
        log("session established")

    def rest_spot(self):
        for code, exch, prod, exp in (("NIFTY", "NSE", "cash", ""),):
            try:
                if not self.ledger.take():
                    return 0.0
                r = self.breeze.get_quotes(stock_code=code, exchange_code=exch, product_type=prod,
                                           expiry_date=exp, right="", strike_price="")
                rows = (r or {}).get("Success") or []
                if rows:
                    return float(rows[0].get("ltp") or 0) or float(rows[0].get("previous_close") or 0)
            except Exception as e:
                log(f"spot quote failed: {e}")
        return 0.0

    # ── registry build ─────────────────────────────────────────────────────
    def add(self, key, kind, sym, exch, code, product="", expiry=None, strike=0.0,
            right="", depth=False, hero=False, **extra):
        exp_s = config.ws_expiry(expiry) if expiry else ""
        q, d = self.token(exch, code, product, exp_s,
                          str(int(strike)) if strike else "", right, depth)
        if not q:
            return None
        i = self.reg.add(key, kind, sym, q, strike, right,
                         expiry.isoformat() if expiry else "", depth=bool(d), hero=hero,
                         seg="eq" if exch == "NSE" else "fo", depth_token=d, **extra)
        return i

    def build(self):
        now = config.now_ist()
        self.w0, self.w1 = config.weekly_expiries(now, 2)
        self.mexp = config.monthly_expiry(now)
        log(f"weekly expiry {self.w0} · next {self.w1} · futures {self.mexp}")
        self.add("NIFTY|SPOT", "spot", "NIFTY", "NSE", "NIFTY")
        self.add("NIFTY|FUT", "fut", "NIFTY", "NFO", "NIFTY", "futures", self.mexp, depth=True)
        self.add("INDIAVIX|SPOT", "vix", "INDIAVIX", "NSE", "INDVIX")
        for name in ("BANKNIFTY", "FINNIFTY"):
            ok = False
            for code in ([self.cache["index"].get(name)] if self.cache["index"].get(name) else []) \
                    + universe.INDEX_CODES[name]:
                if self.add(f"{name}|SPOT", "spot", name, "NSE", code) is not None:
                    self.add(f"{name}|FUT", "fut", name, "NFO", code, "futures", self.mexp,
                             depth=(name == "BANKNIFTY"))
                    self.cache["index"][name] = code
                    ok = True
                    break
            if not ok:
                log(f"{name}: no working code among {universe.INDEX_CODES[name]} — absent today")
        spot = self.rest_spot()
        if spot <= 0:
            raise SystemExit("Could not read Nifty spot by REST — session/market issue.")
        self.band_center = round(spot / config.STRIKE_STEP) * config.STRIKE_STEP
        self.add_options(self.band_center)
        for sym, (wn, wb, wf, tag, grp) in universe.STOCKS.items():
            code = self.isec(sym)
            if not code:
                log(f"{sym}: ISEC code unresolved — skipped")
                continue
            self.add(f"{sym}|EQ", "eq", sym, "NSE", code, wn=wn, wb=wb, wf=wf, wtag=tag, group=grp)
            depth = sym in ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "RELIANCE")
            cached = self.cache["fut_exp"].get(sym)
            exps = [datetime.fromisoformat(cached).date()] \
                if cached and cached >= now.date().isoformat() else config.monthly_expiry_candidates(now)
            for e in exps:
                if self.add(f"{sym}|FUT", "sfut", sym, "NFO", code, "futures", e, depth=depth,
                            wn=wn, wb=wb, wf=wf, group=grp) is not None:
                    self.cache["fut_exp"][sym] = e.isoformat()
                    break
        self._save_cache()
        self.reg.save(self.t)
        self.rec.put("reg", time.time_ns(), self.reg.items)
        log(f"{len(self.reg.items)} instruments resolved (spot {spot:.1f}, band centre {self.band_center:.0f})")

    def add_options(self, center):
        for k in range(-config.WEEKLY_BAND, config.WEEKLY_BAND + 1):
            strike = center + k * config.STRIKE_STEP
            for right, rr in (("call", "CE"), ("put", "PE")):
                self.add(f"NIFTY|OPT|{self.w0}|{int(strike)}|{rr}", "opt", "NIFTY", "NFO", "NIFTY",
                         "options", self.w0, strike, right, depth=abs(k) <= config.HERO_BAND + 1,
                         rr=rr, week=0)
        for k in range(-config.NEXTWEEK_BAND, config.NEXTWEEK_BAND + 1):
            strike = center + k * config.STRIKE_STEP
            for right, rr in (("call", "CE"), ("put", "PE")):
                self.add(f"NIFTY|OPT|{self.w1}|{int(strike)}|{rr}", "opt", "NIFTY", "NFO", "NIFTY",
                         "options", self.w1, strike, right, rr=rr, week=1)

    # ── streaming ──────────────────────────────────────────────────────────
    def hook(self):
        from breeze_connect import breeze_connect as bc
        feed = self
        by_token = self.reg.by_token

        def on_message(sock_self, data):          # runs on the SDK's socket threads
            t0 = time.perf_counter_ns()
            recv = time.time_ns()
            feed.last_msg = time.monotonic()
            with feed.lock:                        # SDK dispatches each packet on its own thread
                apply_packet(feed.t, by_token, data, recv)
            feed.rec.put("p", recv, data)
            feed.hot.add((time.perf_counter_ns() - t0) / 1000.0)

        bc.SocketEventBreeze.on_message = on_message

    def subscribe_all(self):
        toks = []
        for it in self.reg.items:
            if it["token"] and it["token"] not in self.subscribed:
                toks.append(it["token"])
            if it.get("depth_token") and it["depth_token"] not in self.subscribed:
                toks.append(it["depth_token"])
        bad = 0
        for k in range(0, len(toks), 50):
            chunk = toks[k:k + 50]
            r = self.breeze.subscribe_feeds(stock_token=chunk)
            if not isinstance(r, dict):
                bad += 1
                log(f"subscribe rejected: {str(r)[:120]}")
            else:
                self.subscribed.update(chunk)
        log(f"subscribed {len(self.subscribed)} streams ({bad} rejected batches)")
        return bad == 0

    def connect(self):
        self.t.set("feed_state", 1)
        for attempt, wait in enumerate((2, 4, 8, 16, 30, 30, 30), 1):
            try:
                drop_stream(self.breeze)         # never reuse a half-dead client
                connect_stream(self.breeze)      # real error text, 15 s wait (SDK: 3 s, one-liner)
                self.subscribed.clear()
                if self.subscribe_all():
                    self.t.set("feed_state", 2)
                    log("websocket LIVE")
                    return True
                log(f"ws connected but subscriptions were rejected ({attempt})")
            except Exception as e:
                hint = stream_hint(str(e))
                log(f"ws connect failed ({attempt}): {e}" + (f" — {hint}" if hint else ""))
            time.sleep(wait)
        self.t.set("feed_state", 4)
        return False

    def reconnect(self):
        self.t.set("feed_state", 3)
        self.t.set("reconnects", int(self.t.c("reconnects")) + 1)
        drop_stream(self.breeze)                # the SDK's ws_disconnect only EMITS an event;
        time.sleep(1)                           # tear the old client down for real
        return self.connect()

    # ── REST poller ────────────────────────────────────────────────────────
    def poller(self):
        last_vix = last_chain = 0.0
        while not int(self.t.c("stop")):
            now = time.monotonic()
            try:
                if now - last_vix >= config.VIX_POLL_S and self.ledger.take():
                    last_vix = now
                    r = self.breeze.get_quotes(stock_code="INDVIX", exchange_code="NSE",
                                               product_type="cash", expiry_date="", right="", strike_price="")
                    rows = (r or {}).get("Success") or []
                    if rows:
                        v = float(rows[0].get("ltp") or 0)
                        if 0 < v < 5:
                            v *= 100
                        if 5 <= v <= 90:
                            self.t.set("vix", v); self.t.set("vix_ns", time.time_ns())
                            self.rec.put("vix", time.time_ns(), v)
                if now - last_chain >= config.CHAIN_POLL_S:
                    last_chain = now
                    self.poll_chain()
            except Exception as e:
                log(f"poller: {e}")
            time.sleep(1.0)

    def poll_chain(self):
        out = {}
        for right in ("call", "put"):
            if not self.ledger.take():
                return
            try:
                r = self.breeze.get_option_chain_quotes(
                    stock_code="NIFTY", exchange_code="NFO", product_type="options",
                    expiry_date=config.rest_expiry(self.w0), right=right, strike_price="")
            except Exception as e:
                log(f"chain {right}: {e}")
                return
            for row in (r or {}).get("Success") or []:
                try:
                    k = float(row.get("strike_price") or 0)
                    oi = float(row.get("open_interest") or 0)
                    if k > 0:
                        out.setdefault(str(int(k)), {})[right] = oi
                except (TypeError, ValueError):
                    pass
        if out:
            payload = {"expiry": self.w0.isoformat(), "oi": out}
            write_chain(self.t, payload)
            self.rec.put("chain", time.time_ns(), payload)

    # ── main loop ──────────────────────────────────────────────────────────
    def run(self):
        self.t.set("feed_state", 1)
        self.login()
        self.build()
        self.hook()
        if not self.connect():
            log("could not connect the websocket — run: python run_apex.py preflight (it prints the real handshake error)")
        threading.Thread(target=self.poller, name="Poller", daemon=True).start()
        try:
            while not int(self.t.c("stop")):
                self.t.set("feed_hb_ns", time.time_ns())
                now = config.now_ist()
                in_mkt = (config.is_trading_day(now.date())
                          and config.mins((9, 15)) <= config.hm(now) <= config.mins((15, 30)))
                if in_mkt and time.monotonic() - self.last_msg > 30:
                    log("no packets for 30 s in market hours — reconnecting")
                    self.last_msg = time.monotonic()
                    self.reconnect()
                self.maybe_recenter()
                time.sleep(0.25)
        except KeyboardInterrupt:               # engineio re-installs SIGINT; treat it as stop
            pass
        self.shutdown()

    def maybe_recenter(self):
        i = self.reg.by_key.get("NIFTY|SPOT")
        if i is None:
            return
        spot = float(self.t.rows["ltp"][i])
        if not spot or spot != spot:
            return
        atm = round(spot / config.STRIKE_STEP) * config.STRIKE_STEP
        if abs(atm - self.band_center) >= config.RECENTER_STRIKES * config.STRIKE_STEP:
            log(f"re-centering option band {self.band_center:.0f} -> {atm:.0f}")
            self.band_center = atm
            self.add_options(atm)
            self.reg.save(self.t)
            self.rec.put("reg", time.time_ns(), self.reg.items)
            self.subscribe_all()

    def shutdown(self):
        drop_stream(self.breeze)                # real teardown (ws_disconnect only emits an event)
        self.rec.stop()
        self.t.set("feed_state", 7)
        log("stopped")


def write_chain(table, payload):
    tmp = os.path.join(config.DATA_DIR, "chain_latest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f)
    replace_retry(tmp, os.path.join(config.DATA_DIR, "chain_latest.json"))
    table.set("chain_version", int(table.c("chain_version")) + 1)
    table.set("chain_ns", table.now_ns())


def main():
    global LOG
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the supervisor's: it sets ctrl.stop
    profile = sys.argv[1] if len(sys.argv) > 1 else ""
    LOG = open(os.path.join(config.LOG_DIR, "feed.log"), "a", encoding="utf-8")
    log(f"starting (TLS trust: {install_trust()})")
    t = Table()
    try:
        BreezeFeed(t, profile).run()
    except SystemExit as e:
        log(str(e)); t.set("feed_state", 4); raise
    except Exception:
        log(traceback.format_exc()); t.set("feed_state", 4); raise


if __name__ == "__main__":
    main()
