"""
GATEWAY process — serves the dashboard and pushes ticks to the browser.

  /                 the dashboard (static files)
  /api/instruments  the instrument list (id -> contract)
  /api/state        the engine's latest state (JSON)
  /ws/ticks         TICK-BY-TICK: polls the shared table every 4 ms and sends
                    only rows whose seqlock counter changed, as compact arrays
                    [id, ltp, bid, ask, bqty, aqty, ttq, oi, age_ms]
                    plus a header with the feed's hot-path timing
  /ws/state         the engine's state, pushed whenever it changes (~4 Hz)
The gateway never computes anything; a slow browser only slows itself.
"""
import asyncio
import json
import os
import time

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .table import StateBlob, Table

app = FastAPI(title="ApexOptions")
T = None
B = None
LAST_STATE = b"{}"


def attach():
    global T, B
    if T is None:
        T = Table()
        B = StateBlob()


def latest_state() -> bytes:
    global LAST_STATE
    _, data = B.read()
    if data:
        LAST_STATE = data
    return LAST_STATE


@app.get("/")
def index():
    return FileResponse(os.path.join(config.STATIC_DIR, "index.html"),
                        headers={"Cache-Control": "no-store"})


@app.get("/api/instruments")
def instruments():
    try:
        with open(config.INSTRUMENTS_JSON, encoding="utf-8") as f:
            d = json.load(f)
        return {"version": d["version"],
                "items": [{k: it.get(k) for k in ("id", "key", "kind", "sym", "strike", "rr", "expiry", "week", "group")}
                          for it in d["items"]]}
    except Exception:
        return {"version": 0, "items": []}


@app.get("/api/state")
def state():
    attach()
    return Response(latest_state(), media_type="application/json")


@app.websocket("/ws/ticks")
async def ws_ticks(ws: WebSocket):
    attach()
    await ws.accept()
    sent = np.zeros(config.MAX_ROWS, dtype=np.uint64)
    last_g = -1
    last_hdr = 0.0
    try:
        while True:
            g = int(T.c("gseq"))
            if g != last_g:
                last_g = g
                rows = T.rows
                seq = rows["seq"].copy()
                ch = np.nonzero((seq != sent) & ((seq & 1) == 0))[0]
                if ch.size:
                    sent[ch] = seq[ch]
                    now = T.now_ns()
                    r = rows[ch]
                    age = (now - r["recv_ns"]) / 1e6
                    out = []
                    for j, i in enumerate(ch.tolist()):
                        out.append([i, _n(r["ltp"][j]), _n(r["bid"][j]), _n(r["ask"][j]), _n(r["bqty"][j]),
                                    _n(r["aqty"][j]), _n(r["ttq"][j]), _n(r["oi"][j]), round(float(age[j]), 1)])
                    await ws.send_text(json.dumps({"r": out, "v": int(T.c("reg_version"))}, separators=(",", ":")))
            t = time.monotonic()
            if t - last_hdr >= 1.0:
                last_hdr = t
                T.set("gateway_hb_ns", time.time_ns())
            await asyncio.sleep(0.004)
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception:
        return


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    attach()
    await ws.accept()
    last = None
    try:
        while True:
            data = latest_state()
            if data is not last:
                last = data
                await ws.send_text(data.decode())
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception:
        return


def _n(x):
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return round(x, 2)


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


def main():
    attach()
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning", ws_ping_interval=20)


if __name__ == "__main__":
    main()
