"""
Dealer gamma map (D-062): where option-market-maker hedging should dampen a move and
where it should amplify it, from the REST option chain's open interest.

Idea (the concept is standard; written here from scratch against our own chain):
  gamma exposure per strike = gamma x open interest x F^2 x 1 %
  calls count +, puts count - (dealers are ASSUMED long calls / short puts against the public)
  balance > 0  -> hedging buys dips and sells rallies (moves dampen, spikes fade)
  balance < 0  -> hedging sells dips and buys rallies (moves amplify, spikes can run)
  flip level   -> the futures price at which the net exposure changes sign

HONESTY NOTES
  * The dealer sign is an assumption, and on Nifty - where retail buys the options - it may be
    wrong. So this is an ADVISOR only: shown, logged on every trade as a would-have verdict, and
    it earns a vote only through the learning loop (D-033), like every other advisor.
  * Open interest units in the REST payload are not relied on: the outputs are LOCATIONS (flip,
    walls, max pain) and a unit-free BALANCE in [-1, +1] = net / gross. No rupee figures.
  * Gamma per strike uses that strike's live implied vol where we have it (the subscribed band),
    otherwise the ATM vol: skew outside the band is ignored.
  * Only the nearest weekly expiry's OI is in the chain payload; the next week is not included.
"""
import math

import numpy as np

from .. import config, greeks

GRID_PCT = 0.03          # scan hypothetical futures prices +-3 % for the flip level
GRID_N = 61
MIN_STRIKES = 6          # fewer usable strikes than this -> no verdict


class GexMap:
    def __init__(self):
        self.key = None            # (chain version, rounded spot) of the last computation
        self.v = {"ok": False, "why": "waiting for the option chain"}

    # ── pure computation ────────────────────────────────────────────────────
    @staticmethod
    def _net_at(F_hyp, ks, ce_oi, pe_oi, T, iv, F_ref):
        """Net signed gamma exposure if the futures were at F_hyp (strikes/IV/OI held fixed)."""
        gm = greeks.greeks(F_hyp, ks, T, iv, np.ones_like(ks, dtype=bool))["gamma"]
        gm = np.nan_to_num(gm, nan=0.0)
        return float(np.sum(gm * (ce_oi - pe_oi)) * F_hyp * F_hyp * 0.01)

    def compute(self, oi, expiry_iso, now_dt, F, iv_by_strike, atm_iv):
        """oi = {"25200": {"call": n, "put": n}}; F = futures/forward; returns the view dict."""
        if not oi or not F or not np.isfinite(F) or not atm_iv:
            return {"ok": False, "why": "no chain / forward / IV yet"}
        T = greeks.years_to_expiry(expiry_iso, now_dt)
        ks = np.array(sorted(float(k) for k in oi))
        ce = np.array([float(oi[str(int(k))].get("call", 0.0) or 0.0) for k in ks])
        pe = np.array([float(oi[str(int(k))].get("put", 0.0) or 0.0) for k in ks])
        keep = (np.abs(ks - F) <= 20 * config.STRIKE_STEP) & ((ce + pe) > 0)
        if keep.sum() < MIN_STRIKES:
            return {"ok": False, "why": "too few strikes with open interest"}
        ks, ce, pe = ks[keep], ce[keep], pe[keep]
        iv = np.array([iv_by_strike.get(float(k)) or atm_iv for k in ks], dtype=float)
        iv = np.where(np.isfinite(iv) & (iv > 0.01), iv, atm_iv)

        gm = np.nan_to_num(greeks.greeks(F, ks, T, iv, np.ones_like(ks, dtype=bool))["gamma"], nan=0.0)
        scale = F * F * 0.01
        cg, pg = gm * ce * scale, gm * pe * scale          # positive magnitudes
        net_k = cg - pg
        gross, net = float(cg.sum() + pg.sum()), float(net_k.sum())
        balance = net / gross if gross > 0 else 0.0

        # walls: gamma falls off fast away from the forward, so "largest exposure" alone would
        # always pick the nearest strike. A wall must first be an OPEN-INTEREST standout on its
        # side (>= 1.5 x the mean of that side), and among those the largest exposure wins.
        up, dn = ks > F, ks < F

        def wall(side, oi_side, g_side):
            if not side.any():
                return None
            stand = side & (oi_side >= 1.5 * oi_side[side].mean()) & (g_side > 0)
            return float(ks[stand][np.argmax(g_side[stand])]) if stand.any() else None
        call_wall, put_wall = wall(up, ce, cg), wall(dn, pe, pg)

        # flip: scan hypothetical futures prices, take the sign change nearest the current price
        grid = F * (1.0 + np.linspace(-GRID_PCT, GRID_PCT, GRID_N))
        tot = np.array([self._net_at(x, ks, ce, pe, T, iv, F) for x in grid])
        flip = None
        sc = np.where(np.sign(tot[:-1]) * np.sign(tot[1:]) < 0)[0]
        if sc.size:
            j = sc[np.argmin(np.abs(grid[sc] - F))]
            x0, x1, y0, y1 = grid[j], grid[j + 1], tot[j], tot[j + 1]
            flip = float(x0 - y0 * (x1 - x0) / (y1 - y0))

        # max pain: strike where the total intrinsic paid to option holders is smallest
        pay = [float(np.sum(ce * np.maximum(s - ks, 0)) + np.sum(pe * np.maximum(ks - s, 0))) for s in ks]
        pain = float(ks[int(np.argmin(pay))])

        if abs(balance) < 0.10:
            regime = "MIXED"
        else:
            regime = "DAMPEN" if balance > 0 else "AMPLIFY"
        return {"ok": True, "regime": regime, "balance": round(balance, 3), "flip": flip,
                "call_wall": call_wall, "put_wall": put_wall, "max_pain": pain,
                "F": float(F), "T_days": round(T * 365, 2), "expiry": expiry_iso,
                "strikes": [[float(k), round(float(a / gross), 4) if gross else 0.0] for k, a in zip(ks, net_k)]}

    # ── cadence: recompute when the chain changes or the forward has moved 10 pts ──
    def update(self, chain_version, oi, expiry_iso, now_dt, F, iv_by_strike, atm_iv):
        k = (chain_version, round(F / 10.0) if F and np.isfinite(F) else None)
        if k != self.key:
            self.key = k
            try:
                self.v = self.compute(oi, expiry_iso, now_dt, F, iv_by_strike, atm_iv)
            except Exception as e:                       # an observer: a bad chain must not stop the loop
                self.v = {"ok": False, "why": f"gex error: {e}"}
        return self.v

    # ── the advisor: does the gamma regime argue against buying this direction now? ──
    def advise(self, d, fut):
        """fut = live Nifty FUTURES (the strikes and the map are in forward space, not cash spot)."""
        v = self.v
        if not v.get("ok") or not fut:
            return False, "no gamma map yet"
        if v["regime"] == "DAMPEN":
            # hedging leans against the move. The one escape: the flip lies AHEAD in the trade
            # direction and close enough (< 30 pts) that the move would cross into the amplifying
            # zone - then hedging turns from brake to accelerator once it is crossed.
            fl = v.get("flip")
            ahead = fl is not None and 0 < (fl - fut) * d < 30
            if not ahead:
                return True, f"gamma DAMPENS moves (balance {v['balance']:+.2f}): spikes tend to fade"
        wall = v.get("call_wall") if d > 0 else v.get("put_wall")
        if wall is not None and 0 < (wall - fut) * d < 20:
            return True, f"{'call' if d > 0 else 'put'} gamma wall {wall:.0f} is only {abs(wall - fut):.0f} pts ahead"
        why = f"gamma {v['regime'].lower()} (balance {v['balance']:+.2f})"
        if v.get("flip"):
            why += f", flip {v['flip']:.0f}"
        return False, why
