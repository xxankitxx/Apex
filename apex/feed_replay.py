"""
REPLAY feed — plays a recorded day (data/ticks/YYYY-MM-DD.jsonl.gz, written by the
live feed or `sim --record`) back through the SAME parser, at any speed.

The recorded receive time becomes the system clock, so the engine, the paper
books and the dashboard behave exactly as they did (or would have) live. This is
how a changed rule is checked against real sessions before it is trusted.

Run via:  python run_apex.py replay data/ticks/2026-10-19.jsonl.gz [--speed 20]
"""
import argparse
import gzip
import json
import os
import time
from datetime import datetime

from . import config
from .feed_breeze import write_chain
from .feed_core import HotStats, Registry, apply_packet
from .table import Table

LOG = None


def log(msg):
    line = f"{datetime.now(config.IST).strftime('%H:%M:%S')} REPLAY {msg}"
    print(line, flush=True)
    try:
        LOG.write(line + "\n"); LOG.flush()
    except Exception:
        pass


def install_registry(table, items, version):
    tmp = config.INSTRUMENTS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": version, "items": items}, f)
    os.replace(tmp, config.INSTRUMENTS_JSON)
    table.set("reg_version", version)
    return Registry.tokens_from_items(items)


def run(path, speed):
    t = Table()
    t.set("speed", speed)
    t.set("feed_state", 6)
    hot = HotStats(t)
    by_token = None
    version = 0
    n = 0
    real0 = v0 = None
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        it = iter(f)
        while True:
            try:
                line = next(it)
            except StopIteration:
                break
            except (EOFError, OSError) as e:          # a recording cut off by a crash
                log(f"recording ends early: {e}")
                break
            if int(t.c("stop")):
                break
            try:
                r = json.loads(line)
            except Exception:
                continue
            k, vns, d = r.get("k"), int(r.get("t", 0)), r.get("d")
            if real0 is None:
                real0, v0 = time.perf_counter(), vns
            sp = max(float(t.c("speed")), 0.1)
            due = real0 + (vns - v0) / 1e9 / sp
            lag = due - time.perf_counter()
            if lag > 0.002:
                time.sleep(lag)
            elif lag < -2.0:
                real0, v0 = time.perf_counter(), vns
            t.set("now_ns", vns)
            if k == "reg":
                version += 1
                by_token = install_registry(t, d, version)
                log(f"registry: {len(d)} instruments")
            elif k == "p" and by_token is not None:
                t0 = time.perf_counter_ns()
                apply_packet(t, by_token, d, vns)
                hot.add((time.perf_counter_ns() - t0) / 1000.0)
                n += 1
            elif k == "chain":
                write_chain(t, d)
            elif k == "vix":
                t.set("vix", float(d)); t.set("vix_ns", vns)
            t.set("feed_hb_ns", time.time_ns())
    # let the engine see the close and finish the day
    time.sleep(1.5)
    t.set("feed_state", 7)
    log(f"done: {n} packets")


def main():
    global LOG
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the supervisor's: it sets ctrl.stop
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--speed", type=float, default=10.0)
    a = ap.parse_args()
    LOG = open(os.path.join(config.LOG_DIR, "replay.log"), "a", encoding="utf-8")
    run(a.file, a.speed)


if __name__ == "__main__":
    main()
