"""
Pressure zones (G2, v1 subset) and the force detector (G3, v1 subset).

PRESSURE — from the REST option chain (every ~90 s):
  * CE walls above spot = resistance; PE walls below = support
    (wall = OI >= 2x the mean of its +-3 neighbours AND in the top quartile of ATM+-10)
  * the destination in a direction = the next wall that way; "room" = distance to it
  * near-ATM PCR (+-6 strikes)
FORCE — on the Nifty-futures book, at the nearest level (a wall mapped into futures
  points by the live basis, session high/low, round 100s):
  idle -> testing (futures within +-5 pts) -> HOLD-STRONG / WEAKENING /
  BREAK-IMMINENT / VACUUM -> BROKE (beyond 5 pts for 30 s) or REJECTED
  measured on window totals of the opposing side:
    S0 = opposing standing qty when the test began, C = aggressive volume into it,
    residual = S - (S0 - C): >0 refill (rho = refill/C), <0 pull (pi = pull/S0)
Both are ADVISORY in v1 (D-033): they are shown, logged on every trade as
"would-have" verdicts, and earn a vote only through the learning loop.
"""
import json
import os

import numpy as np

from .. import config


class Pressure:
    def __init__(self):
        self.version = -1
        self.walls_up = []     # [(strike, oi)] CE walls
        self.walls_dn = []     # PE walls
        self.pcr = None
        self.chain_age = None
        self.oi = {}
        self.oi0 = {}
        self.expiry = None     # ISO date of the expiry the chain's OI belongs to

    def chain_view(self, spot, n=10):
        """[[strike, ce_oi, pe_oi, ce_chg_since_open, pe_chg_since_open]] for ATM +- n."""
        if not self.oi or not spot or spot != spot:
            return []
        atm = round(spot / config.STRIKE_STEP) * config.STRIKE_STEP
        out = []
        for k in sorted(self.oi, key=float):
            kf = float(k)
            if abs(kf - atm) > n * config.STRIKE_STEP:
                continue
            v, v0 = self.oi[k], self.oi0.get(k, {})
            ce, pe = float(v.get("call", 0)), float(v.get("put", 0))
            out.append([kf, ce, pe, ce - float(v0.get("call", ce)), pe - float(v0.get("put", pe))])
        return out

    def refresh(self, table, spot):
        v = int(table.c("chain_version"))
        if v != self.version:
            self.version = v
            try:
                with open(os.path.join(config.DATA_DIR, "chain_latest.json")) as f:
                    chain = json.load(f)
                self.oi = chain.get("oi", {})
                self.expiry = chain.get("expiry")
            except Exception:
                self.oi = {}
                self.expiry = None
            if self.oi and not self.oi0:
                self.oi0 = {k: dict(v) for k, v in self.oi.items()}   # first chain of the session
        cns = int(table.c("chain_ns"))
        self.chain_age = (table.now_ns() - cns) / 1e9 if cns else None
        if not self.oi or not spot or spot != spot:
            return
        ks = np.array(sorted(float(k) for k in self.oi))
        ce = np.array([self.oi[str(int(k))].get("call", 0.0) for k in ks])
        pe = np.array([self.oi[str(int(k))].get("put", 0.0) for k in ks])
        atm = round(spot / config.STRIKE_STEP) * config.STRIKE_STEP
        near = np.abs(ks - atm) <= 10 * config.STRIKE_STEP
        self.walls_up = self._walls(ks, ce, near, lambda k: k > spot)
        self.walls_dn = self._walls(ks, pe, near, lambda k: k < spot)
        n6 = np.abs(ks - atm) <= 6 * config.STRIKE_STEP
        self.pcr = float(pe[n6].sum() / ce[n6].sum()) if ce[n6].sum() > 0 else None

    @staticmethod
    def _walls(ks, oi, near, side):
        if not near.any():
            return []
        q75 = np.percentile(oi[near], 75)
        out = []
        for j, k in enumerate(ks):
            if not near[j] or not side(k):
                continue
            nb = [oi[x] for x in range(max(0, j - 3), min(len(ks), j + 4)) if x != j]
            if oi[j] > 0 and oi[j] >= q75 and nb and oi[j] >= 2.0 * np.mean(nb):
                out.append((float(k), float(oi[j])))
        return out

    def destination(self, spot, d):
        walls = self.walls_up if d > 0 else self.walls_dn
        cands = [k for k, _ in walls if (k - spot) * d > 0]
        if not cands:
            return None
        k = min(cands, key=lambda x: abs(x - spot))
        return {"level": k, "room": abs(k - spot)}

    def view(self, spot):
        return {"walls_up": self.walls_up[:4], "walls_dn": sorted(self.walls_dn, reverse=True)[:4],
                "pcr": self.pcr, "chain_age": self.chain_age,
                "dest_up": self.destination(spot, 1) if spot else None,
                "dest_dn": self.destination(spot, -1) if spot else None}


class Force:
    BAND = 5.0          # futures points
    BREAK_HOLD_S = 30.0

    def __init__(self):
        self.test = None
        self.verdict = "IDLE"
        self.last_closed = None
        self.sess_hi = -np.inf
        self.sess_lo = np.inf

    def levels(self, fut, spot, pressure):
        basis = (fut - spot) if (spot and spot == spot) else 0.0
        lv = [(k + basis, f"{int(k)} CE wall") for k, _ in pressure.walls_up]
        lv += [(k + basis, f"{int(k)} PE wall") for k, _ in pressure.walls_dn]
        base = round(fut / 100.0) * 100.0
        lv += [(base + x, f"{int(base + x)} round") for x in (-100, 0, 100)]
        if np.isfinite(self.sess_hi):
            lv.append((self.sess_hi, "session high"))
            lv.append((self.sess_lo, "session low"))
        return lv

    def update(self, m, flow, fut_id, spot, pressure, coherence, now_s):
        if fut_id is None:
            return
        fut = float(m.ltp[fut_id, m.k])
        if not np.isfinite(fut):
            return
        lvls = self.levels(fut, spot, pressure)
        self.sess_hi = max(self.sess_hi, fut)
        self.sess_lo = min(self.sess_lo, fut)
        t = self.test
        if t is None:
            near = [(abs(fut - L), L, name) for L, name in lvls if abs(fut - L) <= self.BAND]
            if not near:
                self.verdict = "IDLE"
                return
            _, L, name = min(near)
            d = 1 if L >= fut else -1          # +1: resistance above (attack from below)
            S0 = float(m.ss[fut_id, m.k] if d > 0 else m.sb[fut_id, m.k])
            self.test = t = {"level": L, "name": name, "dir": d, "t0": now_s, "S0": S0,
                             "C": 0.0, "beyond_since": None, "rho": None, "pi": None,
                             "attacks": 0, "peak_A": 0.0}
        d = t["dir"]
        S = float(m.ss[fut_id, m.k] if d > 0 else m.sb[fut_id, m.k])
        A = float(flow.agg_b[fut_id] if d > 0 else flow.agg_s[fut_id])
        t["C"] += A * 0.1
        t["peak_A"] = max(t["peak_A"], A)
        S0, C = t["S0"], t["C"]
        resid = S - (S0 - C) if np.isfinite(S) and S0 > 0 else 0.0
        t["rho"] = (max(resid, 0.0) / C) if C > 0 else None
        t["pi"] = (max(-resid, 0.0) / S0) if S0 > 0 else None
        beyond = (fut - t["level"]) * d
        if beyond >= self.BAND:
            t["beyond_since"] = t["beyond_since"] or now_s
            if now_s - t["beyond_since"] >= self.BREAK_HOLD_S:
                self._close("BROKE", now_s)
                return
        else:
            t["beyond_since"] = None
        if beyond <= -2 * self.BAND:
            self._close("REJECTED" if t["rho"] is not None and t["rho"] >= 1.0 else "LEFT", now_s)
            return
        rho, pi = t["rho"], t["pi"]
        spread = float(m.snap["ask"][fut_id] - m.snap["bid"][fut_id])
        if pi is not None and pi >= 0.5 and beyond > 0:
            v = "VACUUM"
        elif rho is not None and rho < 0.5 and S0 > 0 and S < 0.4 * S0 and coherence >= 0.6:
            v = "BREAK-IMMINENT"
        elif rho is not None and rho < 0.7 and coherence >= 0.4:
            v = "WEAKENING"
        elif rho is not None and rho >= 1.0 and A < 0.5 * max(t["peak_A"], 1e-9):
            v = "HOLD-STRONG"
        else:
            v = "TESTING"
        self.verdict = v
        t["spread"] = spread

    def _close(self, outcome, now_s):
        t = self.test
        self.last_closed = {"level": t["level"], "name": t["name"], "outcome": outcome,
                            "dur": now_s - t["t0"]}
        self.test = None
        self.verdict = outcome

    def view(self):
        t = self.test
        out = {"verdict": self.verdict, "last": self.last_closed}
        if t:
            out.update({k: t.get(k) for k in ("level", "name", "dir", "S0", "C", "rho", "pi")})
        return out
