"""
Buyers vs sellers — quantity AND number of orders — and how the book relates
to price (G3 §5.4, extended 17 Oct 2026 on the owner's instruction).

Per instrument, from the 5-level depth (best level only where depth isn't
subscribed) and the whole-book totals every quote carries:

  standing buyers   : qty  sb, orders sbo, average order size sb/sbo
  standing sellers  : qty  ss, orders sso, average order size ss/sso
  whole book        : tbq / tsq (every resting order on the exchange book)
  aggressive volume : each Δttq classified against the previous quote —
                      at/through the ask = buyer, at/through the bid = seller

Rate classes (the owner's "falling slowly or fast"), computed separately for
the QUANTITY and for the NUMBER OF ORDERS on each side:
  REFILLING · HOLDING · DRAIN-SLOW · DRAIN-FAST · PULLED
  PULLED = the side shrank fast and trades explain < 25 % of the shrink: the
  sellers LEFT, they were not eaten. On the order-count series this is the
  cleanest "sellers walking away" signal there is — fills remove quantity,
  cancellations remove orders.

Imbalances, each in [-1, +1] (+ = buyers heavier):
  imb_q  on 5-level quantity · imb_o on order counts · imb_t on the whole book

Book-leads-price score  lead ∈ [-1, 1]:
  an exponentially weighted correlation between the order-count imbalance
  TWO SECONDS AGO and the price change SINCE then. +0.3 or more means the
  standing orders on this contract have been predicting its next move; near 0
  means the book is noise here (market-maker quotes), and the owner's
  buyers-vs-sellers reading should carry no weight for this contract right now.

Every value is per contract, every 100 ms, with its age; a stale instrument
gets no class.
"""
import math

import numpy as np

from .market import HZ

CLS = ["—", "REFILLING", "HOLDING", "DRAIN-SLOW", "DRAIN-FAST", "PULLED"]
UNK, REFILL, HOLD, DSLOW, DFAST, PULL = range(6)
DRAIN_W = {UNK: 0, REFILL: -1, HOLD: 0, DSLOW: 1, DFAST: 2, PULL: 3}


def _ew(prev, x, dt, half_life):
    a = 1.0 - np.exp(-dt * math.log(2) / half_life)
    return np.where(np.isfinite(prev), prev + a * (x - prev), x)


def _imb(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where((a + b) > 0, (a - b) / (a + b), np.nan)


class Flow:
    def __init__(self, n):
        self.n = n
        self.agg_b = np.zeros(n)     # aggressive buy volume, EWMA per second (h 10 s)
        self.agg_s = np.zeros(n)
        self.unc = np.zeros(n)
        self.vol_s = np.full(n, np.nan)       # volume per second EWMA (h 5 s)
        self.vol_base = np.full(n, np.nan)    # volume per second EWMA (h 5 min) — baseline
        self.agg10_b = np.zeros(n)            # raw sums over the last 10 s (ring) for consumption
        self.agg10_s = np.zeros(n)
        self._rb = np.zeros((n, 10 * HZ))
        self._rs = np.zeros((n, 10 * HZ))
        self._k = 0
        # classes on quantity and on order counts, both sides
        self.cls_b = np.zeros(n, int)
        self.cls_s = np.zeros(n, int)
        self.cls_bo = np.zeros(n, int)
        self.cls_so = np.zeros(n, int)
        # imbalances
        self.imb_q = np.full(n, np.nan)
        self.imb_o = np.full(n, np.nan)
        self.imb_t = np.full(n, np.nan)
        self.imb_t_chg = np.full(n, np.nan)   # whole-book imbalance change over 30 s
        self.avg_b = np.full(n, np.nan)       # average resting order size, buy side
        self.avg_s = np.full(n, np.nan)
        # book-leads-price: EW moments of (imbalance 2 s ago, price change since)
        self._mx = np.zeros(n); self._my = np.zeros(n)
        self._vx = np.zeros(n); self._vy = np.zeros(n); self._cxy = np.zeros(n)
        self.lead = np.zeros(n)
        self.last_dt = 0.1

    def update(self, m, dt: float):
        s, p = m.snap, m.prev_snap
        if p is None:
            return
        dq = s["ttq"] - p["ttq"]
        dq = np.where(np.isfinite(dq) & (dq > 0), dq, 0.0)
        last = s["ltp"]
        pa, pb, pl = p["ask"], p["bid"], p["ltp"]
        buy = (dq > 0) & (pa > 0) & (last >= pa)
        sell = (dq > 0) & (pb > 0) & (last <= pb) & ~buy
        mid = (dq > 0) & ~buy & ~sell
        up = mid & (last > pl)
        dn = mid & (last < pl)
        vb = np.where(buy | up, dq, 0.0)
        vs = np.where(sell | dn, dq, 0.0)
        vu = np.where(mid & ~up & ~dn, dq, 0.0)
        rate = 1.0 / max(dt, 1e-3)
        self.agg_b = _ew(self.agg_b, vb * rate, dt, 10.0)
        self.agg_s = _ew(self.agg_s, vs * rate, dt, 10.0)
        self.unc = _ew(self.unc, vu * rate, dt, 10.0)
        self.vol_s = _ew(self.vol_s, dq * rate, dt, 5.0)
        self.vol_base = _ew(self.vol_base, dq * rate, dt, 300.0)
        self._k = (self._k + 1) % self._rb.shape[1]
        self._rb[:, self._k] = vb
        self._rs[:, self._k] = vs
        self.agg10_b = self._rb.sum(axis=1)
        self.agg10_s = self._rs.sum(axis=1)

        k = m.k
        sb, ss, sbo, sso = m.sb[:, k], m.ss[:, k], m.sbo[:, k], m.sso[:, k]
        # quantity classes: bids are consumed by sellers, asks by buyers
        self.cls_b = self._classify(m.sb, m, self.agg10_s)
        self.cls_s = self._classify(m.ss, m, self.agg10_b)
        # order-count classes: a fill of one resting order removes ~avg-size quantity, so the
        # "explained by trades" test is done in order units (consumed qty / average order size)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.avg_b = np.where(sbo > 0, sb / sbo, np.nan)
            self.avg_s = np.where(sso > 0, ss / sso, np.nan)
            cons_b_orders = np.where(np.isfinite(self.avg_b) & (self.avg_b > 0), self.agg10_s / self.avg_b, 0.0)
            cons_s_orders = np.where(np.isfinite(self.avg_s) & (self.avg_s > 0), self.agg10_b / self.avg_s, 0.0)
        self.cls_bo = self._classify(m.sbo, m, cons_b_orders)
        self.cls_so = self._classify(m.sso, m, cons_s_orders)
        # imbalances
        self.imb_q = _imb(sb, ss)
        self.imb_o = _imb(sbo, sso)
        tbq, tsq = s["tbq"].astype(float), s["tsq"].astype(float)
        self.imb_t = _imb(np.where(tbq > 0, tbq, np.nan), np.where(tsq > 0, tsq, np.nan))
        pt = m.imb_t_ago(30)
        self.imb_t_chg = self.imb_t - pt
        # book-leads-price: x = order imbalance 2 s ago (fallback quantity), y = price change since
        j = m.ago(2.0)
        x = _imb(m.sbo[:, j], m.sso[:, j])
        xq = _imb(m.sb[:, j], m.ss[:, j])
        x = np.where(np.isfinite(x), x, xq)
        with np.errstate(divide="ignore", invalid="ignore"):
            y = (m.ltp[:, k] - m.ltp[:, j]) / m.ltp[:, j]
        ok = np.isfinite(x) & np.isfinite(y)
        a = 1.0 - math.exp(-dt * math.log(2) / 180.0)          # 3-minute half-life
        x0 = np.where(ok, x, self._mx); y0 = np.where(ok, y, self._my)
        self._mx += a * (x0 - self._mx); self._my += a * (y0 - self._my)
        dx, dy = x0 - self._mx, y0 - self._my
        self._vx += a * (dx * dx - self._vx); self._vy += a * (dy * dy - self._vy)
        self._cxy += a * (dx * dy - self._cxy)
        with np.errstate(divide="ignore", invalid="ignore"):
            lead = self._cxy / np.sqrt(self._vx * self._vy)
        self.lead = np.where(np.isfinite(lead), np.clip(lead, -1, 1), 0.0)

    @staticmethod
    def _classify(arr, m, consumed10):
        now = arr[:, m.k]
        a10 = arr[:, m.ago(10)]
        a60 = arr[:, m.ago(60)]
        with np.errstate(divide="ignore", invalid="ignore"):
            r10 = np.log(now / a10)
            r60 = np.log(now / a60)
        cls = np.full(arr.shape[0], UNK)
        ok = np.isfinite(r10) & (a10 > 0) & (now > 0)
        cls[ok] = HOLD
        cls[ok & (r10 > 0.15)] = REFILL
        cls[ok & np.isfinite(r60) & (r60 <= -0.30) & (r10 > -0.40)] = DSLOW
        fast = ok & (r10 <= -0.40)
        cls[fast] = DFAST
        drop = np.where(ok, a10 - now, 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            explained = np.where(drop > 0, consumed10 / drop, 1.0)
        cls[fast & (r10 <= -0.50) & (explained < 0.25)] = PULL
        return cls

    def side(self, i, direction):
        """The OPPOSING side's state for a contract that should move in `direction`
        (+1: the asks oppose a rising price). Returns (qty class, orders class, imbalance for)."""
        imb = float(self.imb_o[i]) if np.isfinite(self.imb_o[i]) else 0.0
        if direction > 0:
            return int(self.cls_s[i]), int(self.cls_so[i]), imb
        return int(self.cls_b[i]), int(self.cls_bo[i]), -imb

    def run_score(self, i, direction, m):
        """'Sellers falling while the price runs' for a contract, in about [-1, 1].
        Price velocity, drain of the opposing side's QUANTITY and of its NUMBER OF ORDERS,
        aggressive flow, and the order imbalance; the book's own lead score decides how much
        the book terms are worth on this contract right now."""
        cq, co, imb = self.side(i, direction)
        drain_q = DRAIN_W[cq] / 3.0
        drain_o = DRAIN_W[co] / 3.0
        tot = self.agg_b[i] + self.agg_s[i]
        agg = ((self.agg_b[i] - self.agg_s[i]) / tot) if tot > 0 else 0.0
        agg *= direction
        v = m.change(m.ltp, 5)[i] / 5.0 * direction
        v = 0.0 if not np.isfinite(v) else max(-1.0, min(1.0, v / 0.5))
        trust = 0.5 + 0.5 * max(0.0, float(self.lead[i]))         # 0.5 .. 1.0
        book = 0.25 * drain_q + 0.25 * drain_o + 0.15 * imb + 0.1 * (1.0 if (cq == PULL or co == PULL) else 0.0)
        return 0.25 * v + 0.25 * agg + trust * book
