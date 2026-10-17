"""
The extra eyes added 17 Oct 2026 (owner: "go ahead and add them"). All of
them are ADVISORS or RECORDS — they vote only after the learning loop proves
them (D-033/D-051), except the basket-gap and book-exit rules, which trade
their own pre-registered paper books (config.VARIANTS).

  Straddle   ATM CE+PE premium vs its own intraday VWAP: is premium being
             BOUGHT (expanding, above VWAP) or SOLD (compressing, below)?
  BankLead   Nifty-Bank futures 15-s impulse on its own 20-min scale: a second
             leader for the domino (banks are ~34 % of Nifty).
  Lag        measured domino lag per episode: first heavyweight crossing to the
             futures crossing. Median for the day is published and recorded.
  Events     owner-maintained calendar (config.EVENT_DAYS): RBI policy, Budget,
             a heavyweight's results — logged as a would-veto advisor.
  Episodes   counterfactual log: for every episode, the hero grid (CE/PE,
             ATM ± 3) at onset and at +15/30/60/120/300 s, the champion's
             verdict at onset and every advisor's vote — traded or not — so the
             learning loop can later tune strike choice and exits on what the
             market actually did, not only on the trades that happened.
"""
import json
import math
import os
from collections import deque

import numpy as np

from .. import config


class Straddle:
    def __init__(self):
        self.px = None          # latest ATM straddle premium
        self.vwap = None
        self._pv = 0.0
        self._v = 0.0
        self.hist = deque(maxlen=900)   # (t, px) at 1 Hz
        self.state = "—"
        self.slope5 = None
        self.atm = None
        self._last_1hz = 0.0

    def update(self, m, snap, key, atm, w0, now_s):
        if atm is None:
            return
        ce = key.get(f"NIFTY|OPT|{w0}|{int(atm)}|CE")
        pe = key.get(f"NIFTY|OPT|{w0}|{int(atm)}|PE")
        if ce is None or pe is None:
            return
        pc, pp = m.ltp[ce, m.k], m.ltp[pe, m.k]
        if not (np.isfinite(pc) and np.isfinite(pp)):
            return
        if self.atm != atm:                      # the strike rolled with spot: restart the VWAP
            self.atm, self._pv, self._v, self.hist = atm, 0.0, 0.0, deque(maxlen=900)
        self.px = float(pc + pp)
        if m.prev_snap is not None:
            dv = float(max(snap["ttq"][ce] - m.prev_snap["ttq"][ce], 0) + max(snap["ttq"][pe] - m.prev_snap["ttq"][pe], 0))
            if dv > 0:
                self._pv += self.px * dv
                self._v += dv
        self.vwap = self._pv / self._v if self._v > 0 else None
        if now_s - self._last_1hz >= 1.0:
            self._last_1hz = now_s
            self.hist.append((now_s, self.px))
        old = [p for t, p in self.hist if t <= now_s - 300]
        self.slope5 = (self.px - old[-1]) if old else None
        if self.vwap:
            above = self.px > self.vwap
            rising = (self.slope5 or 0.0) > 0
            self.state = ("EXPANDING" if rising else "ABOVE VWAP") if above else ("COMPRESSING" if not rising else "BELOW VWAP")

    def veto(self):
        """Premium is being sold: below its VWAP and lower than 5 minutes ago."""
        return bool(self.vwap and self.px is not None and self.px < self.vwap and (self.slope5 or 0.0) < 0)

    def view(self):
        return {"px": self.px, "vwap": self.vwap, "state": self.state, "slope5": self.slope5, "atm": self.atm}


class BankLead:
    """Nifty-Bank futures 15-s impulse on its own scale, and whether it crossed before Nifty."""

    def __init__(self):
        self.sig = 60.0
        self.n = 0
        self.z = 0.0
        self._last_1hz = 0.0
        self.cross_t = None
        self._ep = None

    def update(self, m, bn_id, now_s, episode):
        if bn_id is None:
            return
        r = m.change(m.ltp, 15)[bn_id]
        if not np.isfinite(r):
            return
        if now_s - self._last_1hz >= 1.0:
            self._last_1hz = now_s
            self.n += 1
            a = max(1.0 / (self.n + 1), 1 - math.exp(-math.log(2) / config.SIGMA_HALF_LIFE_S))
            self.sig += a * (abs(float(r)) - self.sig)
        self.z = float(r) / max(self.sig, 2.0)
        ep_id = episode["id"] if episode else None
        if ep_id != self._ep:
            self._ep, self.cross_t = ep_id, None
        if episode and self.cross_t is None and self.z * episode["dir"] >= 2.0:
            self.cross_t = now_s

    def veto(self, d):
        return self.z * d < -0.5

    def view(self):
        return {"z": round(self.z, 2), "sigma": round(self.sig, 1), "cross_t": self.cross_t}


class LagMeter:
    """Per-episode domino lag (first stock crossing → futures crossing), day median."""

    def __init__(self):
        self.lags = []
        self._seen = set()

    def update(self, ep):
        if not ep or ep["id"] in self._seen:
            return
        ft, sc = ep.get("fut_cross_t"), ep.get("stock_cross") or {}
        if ft is not None and sc:
            self._seen.add(ep["id"])
            self.lags.append(round(ft - min(sc.values()), 2))

    def view(self):
        if not self.lags:
            return {"n": 0, "median": None, "last": None}
        return {"n": len(self.lags), "median": float(np.median(self.lags)), "last": self.lags[-1]}


def event_today(day: str):
    return config.EVENT_DAYS.get(day)


class EpisodeLog:
    """Counterfactual grid snapshots per episode → data/paper/episodes_DAY.jsonl."""
    OFFSETS = (0, 15, 30, 60, 120, 300)

    def __init__(self, day):
        self.path = os.path.join(config.PAPER_DIR, f"episodes_{day}.jsonl")
        self.open = {}          # ep id -> {"t0", "done": set(), "rec": {...}}
        self.count = 0

    def grid(self, ctx, engine):
        atm = getattr(engine, "atm", None)
        if atm is None:
            return []
        out = []
        for k in range(-3, 4):
            strike = int(atm + k * config.STRIKE_STEP)
            for rr in ("CE", "PE"):
                o = ctx["by_key"].get(f"NIFTY|OPT|{engine.w0}|{strike}|{rr}")
                if not o:
                    continue
                i = o["id"]
                g = engine.greek.get(i, {})
                cq, co, imb = engine.flow.side(i, 1 if rr == "CE" else -1)
                out.append({"k": strike, "rr": rr, "ltp": o["ltp"], "bid": o["bid"], "ask": o["ask"],
                            "iv": g.get("iv"), "delta": g.get("delta"), "oi": float(engine.m.snap["oi"][i]),
                            "sell_cls": int(cq), "sell_ord_cls": int(co), "imb_o": round(imb, 3),
                            "lead": round(float(engine.flow.lead[i]), 3)})
        return out

    def update(self, ctx, engine):
        ep = ctx.get("episode")
        now = ctx["now_s"]
        if ep and ep["id"] not in self.open:
            self.open[ep["id"]] = {"t0": now, "done": set(), "rec": {
                "ep": ep["id"], "day": engine.day, "t_onset": ctx["now_dt"].strftime("%H:%M:%S"),
                "dir": ep["dir"], "type": ep["type"], "first": ep["first"], "fut0": ctx["fut"],
                "verdict_at_onset": engine.last_reason, "advisors": {k: bool(v.get("veto")) for k, v in ctx["advisors"].items()},
                "straddle": engine.straddle.view(), "bank_z": engine.bank.z, "snaps": {}}}
        for ep_id, st in list(self.open.items()):
            age = now - st["t0"]
            for off in self.OFFSETS:
                if off not in st["done"] and age >= off:
                    st["done"].add(off)
                    st["rec"]["snaps"][str(off)] = {"fut": ctx["fut"], "grid": self.grid(ctx, engine)}
                    if ep and ep["id"] == ep_id:
                        st["rec"]["type"] = ep["type"]; st["rec"]["first"] = ep["first"]
            if len(st["done"]) == len(self.OFFSETS):
                self._flush(st["rec"]); del self.open[ep_id]

    def _flush(self, rec):
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            self.count += 1
        except Exception:
            pass

    def close(self):
        for st in list(self.open.values()):
            self._flush(st["rec"])
        self.open.clear()
