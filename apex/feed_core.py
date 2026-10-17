"""
Feed core — shared by the live Breeze feed, the synthetic simulator and the
replayer, so all three drive the system through ONE parser.

Raw Breeze packet layouts (verified in breeze_connect 1.0.69 `parse_data`):
  quote, NSE cash  : 21-element list, symbol "4.1!<token>"
     [symbol, open, last, high, low, change, bPrice, bQty, sPrice, sQty, ltq,
      avgPrice, ttq, totalBuyQt, totalSellQ, ttv, trend, lowerCkt, upperCkt,
      ltt_epoch, close]
  quote, NFO       : 23-element list
     [... avgPrice(11), OI(12), CHNGOI(13), ttq(14), totalBuyQt(15),
      totalSellQ(16), ttv(17), trend(18), lowerCkt(19), upperCkt(20),
      ltt_epoch(21), close(22)]
  depth            : [symbol "4.2!<token>", time_epoch,
                      [[bRate, bQty, bOrders, bFlag, sRate, sQty, sOrders, sFlag] x 5]]
We read the raw list (hooked before the SDK's dict building), keep `ltt` as a
number, and never call strftime on the hot path.
"""
import gzip
import json
import os
import queue
import threading
import time
from collections import deque

import numpy as np

from . import config


def _f(x) -> float:
    try:
        if x is None or x == "":
            return np.nan
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def replace_retry(src, dst, tries=8):
    """os.replace that tolerates a Windows sharing violation while a reader has the file open."""
    for k in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(0.05 * (k + 1))
    os.replace(src, dst)


class Registry:
    """Instrument list. Each instrument: id, key, kind, sym, strike, right,
    expiry, token (quote token, e.g. '4.1!35001'), depth (bool), hero (bool),
    weights."""

    def __init__(self):
        self.items = []
        self.by_key = {}
        self.by_token = {"eq": {}, "fo": {}}   # numeric token -> id, per segment
        self.version = 0

    def add(self, key, kind, sym, token, strike=0.0, right="", expiry="",
            depth=False, hero=False, seg="fo", **extra):
        if key in self.by_key:
            it = self.items[self.by_key[key]]
            it["depth"] = it["depth"] or depth
            it["hero"] = hero
            return it["id"]
        if len(self.items) >= config.MAX_ROWS:
            raise RuntimeError("instrument table full")
        i = len(self.items)
        it = dict(id=i, key=key, kind=kind, sym=sym, token=token, strike=float(strike),
                  right=right, expiry=expiry, depth=bool(depth), hero=bool(hero), seg=seg, **extra)
        self.items.append(it)
        self.by_key[key] = i
        if token:
            self.by_token[seg][str(token).split("!")[-1]] = i
        return i

    @staticmethod
    def tokens_from_items(items):
        bt = {"eq": {}, "fo": {}}
        for it in items:
            if it.get("token"):
                bt[it.get("seg", "fo")][str(it["token"]).split("!")[-1]] = it["id"]
        return bt

    def save(self, table=None):
        self.version += 1
        tmp = config.INSTRUMENTS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": self.version, "items": self.items}, f)
        replace_retry(tmp, config.INSTRUMENTS_JSON)
        if table is not None:
            table.set("reg_version", self.version)

    @staticmethod
    def load():
        with open(config.INSTRUMENTS_JSON, encoding="utf-8") as f:
            return json.load(f)


class HotStats:
    """Per-second hot-path timing (µs), published to the control block."""

    def __init__(self, table):
        self.t = table
        self.buf = deque(maxlen=20000)
        self.n = 0
        self.last = time.monotonic()

    def add(self, us: float):
        self.buf.append(us)
        self.n += 1
        now = time.monotonic()
        if now - self.last >= 1.0:
            a = np.fromiter(self.buf, float) if self.buf else np.zeros(1)
            self.t.set("hot_p50_us", float(np.percentile(a, 50)))
            self.t.set("hot_p99_us", float(np.percentile(a, 99)))
            self.t.set("hot_max_us", float(a.max()))
            self.t.set("msgs_per_s", self.n / (now - self.last))
            self.buf.clear()
            self.n = 0
            self.last = now


def apply_packet(table, by_token, raw, recv_ns: int) -> int:
    """Write one raw Breeze packet into the table. Returns row id or -1.
    by_token = {"eq": {tok: id}, "fo": {tok: id}} — NSE cash and NFO share the
    '4.' prefix, so a quote's length (21 cash / 23 F&O) picks the segment."""
    if not isinstance(raw, (list, tuple)) or not raw or not isinstance(raw[0], str):
        return -1
    sym = raw[0]
    if "!" not in sym:
        return -1
    head, tok = sym.split("!", 1)
    kind = head.split(".")[-1] if "." in head else "1"
    n = len(raw)
    if kind == "1":
        i = by_token["fo" if n == 23 else "eq"].get(tok, -1)
    else:
        i = by_token["fo"].get(tok, by_token["eq"].get(tok, -1))
    if i < 0:
        return -1
    r = table.rows
    if kind == "1" and n in (21, 23):
        ltp = _f(raw[2])
        ttq_new = _f(raw[14] if n == 23 else raw[12])
        old_ttq = r["ttq"][i]
        # monotonic guard: a quote older than what we hold (SDK reordering) is dropped
        if ttq_new == ttq_new and old_ttq > 0 and ttq_new < old_ttq:
            return -1
        table.begin(i)
        if ltp == ltp and ltp > 0:
            r["ltp"][i] = ltp
        r["open"][i] = _f(raw[1]); r["high"][i] = _f(raw[3]); r["low"][i] = _f(raw[4])
        r["bid"][i] = _f(raw[6]); r["bqty"][i] = _f(raw[7])
        r["ask"][i] = _f(raw[8]); r["aqty"][i] = _f(raw[9])
        r["avg"][i] = _f(raw[11])
        if n == 23:
            oi = _f(raw[12])
            if oi == oi and oi > 0:
                r["oi"][i] = oi
            r["ttq"][i] = ttq_new if ttq_new == ttq_new else old_ttq
            r["tbq"][i] = _f(raw[15]); r["tsq"][i] = _f(raw[16])
            r["ltt"][i] = _f(raw[21]); r["close"][i] = _f(raw[22])
        else:
            r["ttq"][i] = ttq_new if ttq_new == ttq_new else old_ttq
            r["tbq"][i] = _f(raw[13]); r["tsq"][i] = _f(raw[14])
            r["ltt"][i] = _f(raw[19]); r["close"][i] = _f(raw[20])
        table.end(i, recv_ns)
        return i
    if kind == "1" and n >= 6:            # unexpected layout: keep at least the price
        ltp = _f(raw[2])
        if ltp == ltp and ltp > 0:
            table.begin(i)
            r["ltp"][i] = ltp
            table.end(i, recv_ns)
            return i
        return -1
    if kind == "2" and n >= 3 and isinstance(raw[2], (list, tuple)):
        lv = raw[2]
        table.begin(i)
        for k in range(5):
            if k < len(lv) and len(lv[k]) >= 8:
                b = lv[k]
                r["bpx"][i, k] = _f(b[0]); r["bq"][i, k] = _f(b[1]); r["bo"][i, k] = _f(b[2])
                r["apx"][i, k] = _f(b[4]); r["aq"][i, k] = _f(b[5]); r["ao"][i, k] = _f(b[6])
            else:
                r["bpx"][i, k] = r["bq"][i, k] = r["bo"][i, k] = np.nan
                r["apx"][i, k] = r["aq"][i, k] = r["ao"][i, k] = np.nan
        r["depth_ns"][i] = recv_ns
        table.end(i, recv_ns)
        return i
    return -1


class Recorder:
    """Append-only, one gzip file per day: data/ticks/YYYY-MM-DD.jsonl.gz.
    Every raw packet, REST result and registry snapshot, in arrival order,
    with its receive time. The writer is a background thread; the hot path
    only does queue.put_nowait."""

    def __init__(self, day: str, enabled: bool = True, suffix: str = ""):
        self.enabled = enabled
        self.q = queue.Queue(maxsize=1_000_000)
        self.dropped = 0
        self.path = os.path.join(config.TICKS_DIR, f"{day}{suffix}.jsonl.gz")   # ~8x smaller than plain text
        self._stop = threading.Event()
        if enabled:
            self.th = threading.Thread(target=self._run, name="Recorder", daemon=True)
            self.th.start()

    def put(self, kind: str, recv_ns: int, data):
        if not self.enabled:
            return
        try:
            self.q.put_nowait((kind, recv_ns, data))
        except queue.Full:
            self.dropped += 1

    def _run(self):
        with gzip.open(self.path, "at", encoding="utf-8", compresslevel=3) as f:
            last_flush = time.monotonic()
            while not self._stop.is_set() or not self.q.empty():
                try:
                    k, t, d = self.q.get(timeout=0.25)
                    f.write(json.dumps({"k": k, "t": t, "d": d}, separators=(",", ":"), default=str))
                    f.write("\n")
                except queue.Empty:
                    pass
                if time.monotonic() - last_flush > 1.0:
                    f.flush()
                    last_flush = time.monotonic()
            f.flush()

    def stop(self):
        self._stop.set()
        if self.enabled:
            self.th.join(timeout=5)
