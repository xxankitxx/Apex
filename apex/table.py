"""
Shared-memory latest-state table (G5 §5.4, simplified for v1).

One fixed-layout row per instrument, written ONLY by the feed process, read
lock-free by the engine and the gateway. Each row carries a seqlock counter:
the writer makes `seq` odd, writes, makes it even; a reader that sees an odd or
changed `seq` simply re-reads (or takes the next frame).

A small control block in the same segment carries the virtual clock, heartbeats
and feed health. A second segment carries the engine's JSON state for the
gateway (single writer, seq-stamped).
"""
import json
import struct
import time
from multiprocessing import shared_memory

import numpy as np

from . import config

ROW_DTYPE = np.dtype([
    ("seq", "u8"),
    ("recv_ns", "i8"),      # FEED receive time, epoch ns (virtual in replay/sim)
    ("ltt", "f8"),          # exchange last-trade time, epoch seconds (raw, not strftime'd)
    ("ltp", "f8"), ("bid", "f8"), ("ask", "f8"),
    ("bqty", "f8"), ("aqty", "f8"),
    ("ttq", "f8"), ("oi", "f8"),
    ("tbq", "f8"), ("tsq", "f8"),     # total buy / total sell quantity (whole book)
    ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),  # close = previous close
    ("avg", "f8"),
    ("ticks", "f8"),
    ("depth_ns", "i8"),
    ("bpx", "f8", 5), ("bq", "f8", 5), ("bo", "f8", 5),
    ("apx", "f8", 5), ("aq", "f8", 5), ("ao", "f8", 5),
])

CTRL_DTYPE = np.dtype([
    ("magic", "u8"),
    ("gseq", "u8"),            # bumps on every row write
    ("now_ns", "i8"),          # the system clock: wall time live, virtual time in replay/sim
    ("reg_version", "i8"),     # instruments.json version
    ("feed_hb_ns", "i8"),      # feed heartbeat (wall)
    ("engine_hb_ns", "i8"),
    ("gateway_hb_ns", "i8"),
    ("feed_state", "i8"),      # 0 init, 1 connecting, 2 live, 3 reconnecting, 4 dead, 5 sim, 6 replay, 7 done
    ("msgs", "u8"),
    ("reconnects", "i8"),
    ("hot_p50_us", "f8"), ("hot_p99_us", "f8"), ("hot_max_us", "f8"),
    ("msgs_per_s", "f8"),
    ("vix", "f8"), ("vix_ns", "i8"),
    ("chain_version", "i8"), ("chain_ns", "i8"),
    ("rest_today", "i8"),
    ("speed", "f8"),
    ("stop", "i8"),            # supervisor sets 1 to ask children to exit
])

MAGIC = 0xA9E0_0001
CTRL_BYTES = 4096
TABLE_BYTES = CTRL_BYTES + config.MAX_ROWS * ROW_DTYPE.itemsize

FEED_STATES = {0: "INIT", 1: "CONNECTING", 2: "LIVE", 3: "RECONNECTING",
               4: "DEAD", 5: "SIM", 6: "REPLAY", 7: "DONE"}


def _open(name: str, size: int, create: bool):
    if create:
        try:
            old = shared_memory.SharedMemory(name=name)
            old.close()
            try:
                old.unlink()
            except Exception:
                pass
        except FileNotFoundError:
            pass
        try:
            return shared_memory.SharedMemory(name=name, create=True, size=size, track=False)
        except TypeError:   # Python < 3.13
            return shared_memory.SharedMemory(name=name, create=True, size=size)
    try:
        return shared_memory.SharedMemory(name=name, track=False)
    except TypeError:
        return shared_memory.SharedMemory(name=name)


class Table:
    def __init__(self, create: bool = False, name: str = config.SHM_TABLE):
        self.shm = _open(name, TABLE_BYTES, create)
        buf = self.shm.buf
        self.ctrl = np.ndarray((1,), dtype=CTRL_DTYPE, buffer=buf[:CTRL_DTYPE.itemsize])[0:1]
        self.rows = np.ndarray((config.MAX_ROWS,), dtype=ROW_DTYPE, buffer=buf[CTRL_BYTES:TABLE_BYTES])
        if create:
            self.rows[:] = np.zeros(config.MAX_ROWS, dtype=ROW_DTYPE)
            self.ctrl[:] = np.zeros(1, dtype=CTRL_DTYPE)
            self.ctrl["magic"] = MAGIC
            self.ctrl["speed"] = 1.0
        elif int(self.ctrl["magic"][0]) != MAGIC:
            raise RuntimeError("shared table not initialised (start via run_apex.py)")

    # ── control helpers ────────────────────────────────────────────────────
    def c(self, field):
        return self.ctrl[field][0]

    def set(self, field, value):
        self.ctrl[field] = value

    def now_ns(self) -> int:
        v = int(self.ctrl["now_ns"][0])
        return v if v > 0 else time.time_ns()

    # ── writer side (feed only) ────────────────────────────────────────────
    def begin(self, i: int):
        self.rows["seq"][i] += 1          # odd: write in progress

    def end(self, i: int, recv_ns: int):
        r = self.rows
        r["recv_ns"][i] = recv_ns
        r["ticks"][i] += 1
        r["seq"][i] += 1                  # even: stable
        self.ctrl["gseq"] += 1
        self.ctrl["msgs"] += 1

    # ── reader side ────────────────────────────────────────────────────────
    def snapshot(self) -> np.ndarray:
        """Copy of all rows; rows caught mid-write are re-read once."""
        s0 = self.rows["seq"].copy()
        snap = self.rows.copy()
        s1 = self.rows["seq"].copy()
        bad = np.nonzero((s0 != s1) | ((s1 & 1) == 1))[0]
        for _ in range(3):                      # re-read rows that changed or were mid-write
            if not bad.size:
                break
            before = self.rows["seq"][bad].copy()
            snap[bad] = self.rows[bad]
            after = self.rows["seq"][bad]
            bad = bad[(before != after) | ((after & 1) == 1)]
        return snap

    def close(self):
        try:
            self.shm.close()
        except Exception:
            pass

    def unlink(self):
        try:
            self.shm.unlink()
        except Exception:
            pass


class StateBlob:
    """Single-writer JSON blob (engine → gateway)."""
    HDR = struct.Struct("<QI")

    def __init__(self, create: bool = False, name: str = config.SHM_STATE):
        self.shm = _open(name, config.STATE_BYTES, create)
        if create:
            self.shm.buf[:self.HDR.size] = self.HDR.pack(0, 0)
        self._seq = 0

    def write(self, obj) -> None:
        data = json.dumps(obj, separators=(",", ":"), allow_nan=False, default=_default).encode()
        if len(data) > config.STATE_BYTES - self.HDR.size - 16:
            return
        seq, _ = self.HDR.unpack_from(self.shm.buf, 0)
        self.HDR.pack_into(self.shm.buf, 0, seq + 1, 0)            # odd = writing
        self.shm.buf[self.HDR.size:self.HDR.size + len(data)] = data
        self.HDR.pack_into(self.shm.buf, 0, seq + 2, len(data))

    def read(self):
        """Returns (seq, bytes) or (seq, None) if unchanged / mid-write."""
        seq, n = self.HDR.unpack_from(self.shm.buf, 0)
        if seq & 1 or n == 0 or seq == self._seq:
            return seq, None
        data = bytes(self.shm.buf[self.HDR.size:self.HDR.size + n])
        seq2, _ = self.HDR.unpack_from(self.shm.buf, 0)
        if seq2 != seq:
            return seq, None
        self._seq = seq
        return seq, data

    def close(self):
        try:
            self.shm.close()
        except Exception:
            pass

    def unlink(self):
        try:
            self.shm.unlink()
        except Exception:
            pass


def _default(o):
    if isinstance(o, (np.floating,)):
        f = float(o)
        return f if np.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return [_default(x) if isinstance(x, (np.floating, np.integer)) else x for x in o.tolist()]
    raise TypeError(type(o))


def clean(obj):
    """Replace NaN/inf with None recursively so json(allow_nan=False) never fails."""
    if isinstance(obj, float):
        return obj if obj == obj and obj not in (float("inf"), float("-inf")) else None
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.floating):
        return clean(float(obj))
    if isinstance(obj, np.integer):
        return int(obj)
    return obj
