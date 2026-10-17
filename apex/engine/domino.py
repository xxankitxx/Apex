"""
Domino / basket engine (G1, v1 subset).

Every heavyweight's 15-s move is converted into Nifty points by its index
weight; each is normalised by its own 20-minute scale. From that:
  * futures impulse z   — Nifty-futures 15-s move / its own 20-min scale
  * synchrony S_d       — share of tracked Nifty weight moving with direction d,
                          |z_i| >= 1 and volume >= 1.2x its own baseline (once warm)
  * basket-implied move — M_b vs futures move M_f, gap G = M_b - M_f
  * first mover         — crossing clocks: who crossed |z| >= 2 first this episode
  * episode             — onset at |z| >= 1, ends after |z| < 0.5 for 30 s;
                          type BASKET-LED / FUTURES-LED / SINGLE-NAME / CO-FIRST
"""
import math
from datetime import datetime

import numpy as np

from .. import config


class EW:
    """EWMA of |x| with fast start (weight max(1/n, alpha))."""

    def __init__(self, half_life_s, seed=np.nan):
        self.h = half_life_s
        self.v = seed
        self.n = 0

    def add(self, x, dt=1.0):
        if x is None or not np.all(np.isfinite(x)):
            return
        self.n += 1
        a = max(1.0 / (self.n + 1), 1.0 - math.exp(-dt * math.log(2) / self.h))   # the seed counts once
        self.v = x if not np.all(np.isfinite(self.v)) else self.v + a * (x - self.v)


class Domino:
    def __init__(self, items, n_rows):
        self.reload(items, n_rows)
        self.fut_sigma = EW(config.SIGMA_HALF_LIFE_S, config.SIGMA15_SEED)
        self.last_1hz = 0.0
        self.episode = None
        self.quiet_since = None
        self.z = 0.0
        self.r15 = 0.0
        self.state = {}
        self.start_s = None

    def reload(self, items, n_rows):
        self.items = items
        key = {it["key"]: it["id"] for it in items}
        self.fut = key.get("NIFTY|FUT")
        self.spot = key.get("NIFTY|SPOT")
        self.bn_fut = key.get("BANKNIFTY|FUT")
        self.eq = [it for it in items if it["kind"] == "eq" and it.get("wn", 0) > 0]
        self.eq_ids = np.array([it["id"] for it in self.eq], dtype=int)
        self.eq_w = np.array([it["wn"] for it in self.eq], dtype=float)
        self.eq_sym = [it["sym"] for it in self.eq]
        self.all_eq = [it for it in items if it["kind"] == "eq"]
        if not hasattr(self, "sig") or len(self.sig) != len(self.eq_ids):
            self.sig = np.full(len(self.eq_ids), np.nan)
            self.sig_n = np.zeros(len(self.eq_ids))
            self.vol15_base = np.full(len(self.eq_ids), np.nan)

    def price(self, m, i):
        if i is None:
            return np.nan
        return m.ltp[i, m.k]

    def update(self, m, now_s: float):
        if self.start_s is None:
            self.start_s = now_s
        fut_id = self.fut if self.fut is not None and np.isfinite(self.price(m, self.fut)) else self.spot
        if fut_id is None:
            return
        r15_raw = m.change(m.ltp, 15)[fut_id]
        have_r15 = bool(np.isfinite(r15_raw))
        r15 = float(r15_raw) if have_r15 else 0.0
        warm = (now_s - self.start_s) >= config.WARMUP_S
        hm_now = config.hm(datetime.fromtimestamp(now_s, config.IST))
        in_session = config.mins(config.MARKET_OPEN) <= hm_now <= config.mins(config.MARKET_CLOSE)

        # 1 Hz: update the scales (only on real, in-session moves — pre-open zeros would shrink σ)
        if now_s - self.last_1hz >= 1.0:
            self.last_1hz = now_s
            if have_r15 and in_session:
                self.fut_sigma.add(abs(r15))
            if len(self.eq_ids):
                N = self._index_level(m, fut_id)
                mi = self._moves(m, N)
                a = np.abs(mi)
                ok = np.isfinite(a)
                self.sig_n[ok] += 1
                alpha = np.maximum(1.0 / np.maximum(self.sig_n, 1), 1 - math.exp(-math.log(2) / config.SIGMA_HALF_LIFE_S))
                self.sig = np.where(ok & np.isfinite(self.sig), self.sig + alpha * (a - self.sig),
                                    np.where(ok, np.maximum(a, 0.05), self.sig))
                dv = m.change(m.ttq, 15)[self.eq_ids]
                okv = np.isfinite(dv) & (dv >= 0)
                av = 1 - math.exp(-math.log(2) / 600.0)
                self.vol15_base = np.where(okv & np.isfinite(self.vol15_base),
                                           self.vol15_base + av * (dv - self.vol15_base),
                                           np.where(okv, dv, self.vol15_base))

        sigma = max(float(self.fut_sigma.v), 0.5)
        z = r15 / sigma
        self.z, self.r15 = z, r15
        d = 1 if z >= 0 else -1

        N = self._index_level(m, fut_id)
        mi = self._moves(m, N)
        zi = mi / np.maximum(self.sig, 0.05)
        dv = m.change(m.ttq, 15)[self.eq_ids] if len(self.eq_ids) else np.array([])
        with np.errstate(divide="ignore", invalid="ignore"):
            act = dv / self.vol15_base
        act_ok = (act >= config.ACTIVITY_MIN) if warm else np.ones(len(self.eq_ids), bool)
        fresh = np.isfinite(mi)
        wtot = self.eq_w[fresh].sum() if fresh.any() else 0.0

        def sync(direction):
            sel = fresh & (np.sign(mi) == direction) & (np.abs(zi) >= config.RECRUIT_Z) & act_ok
            return float(self.eq_w[sel].sum() / wtot) if wtot > 0 else 0.0

        S_up, S_dn = sync(1), sync(-1)
        Mb = float(np.nansum(mi) * (100.0 / max(wtot, 1e-9))) if wtot > 0 else 0.0
        if len(self.eq_ids) and fresh.any():
            contrib = np.where(fresh, mi, 0.0)
            tot = np.abs(contrib).sum()
            conc = float(np.abs(contrib).max() / tot) if tot > 0 else 0.0
        else:
            conc = 0.0

        self._episode(now_s, z, d, m, fut_id, zi, S_up if d > 0 else S_dn, conc)
        self.state = {
            "z": z, "r15": r15, "sigma15": sigma, "dir": d,
            "S_up": S_up, "S_dn": S_dn, "Mb": Mb, "Mf": r15, "gap": Mb - r15,
            "conc": conc, "coverage": float(wtot), "warm": warm,
            "tiles": [
                {"sym": self.eq_sym[j], "w": float(self.eq_w[j]),
                 "m": _f(mi[j]), "z": _f(zi[j]), "act": _f(act[j]) if len(act) else None}
                for j in range(len(self.eq_ids))
            ],
        }

    def _index_level(self, m, fut_id):
        """Nifty level for converting stock moves into points: spot, else futures."""
        N = self.price(m, self.spot) if self.spot is not None else np.nan
        return N if np.isfinite(N) else self.price(m, fut_id)

    def _moves(self, m, N):
        if not len(self.eq_ids) or not np.isfinite(N):
            return np.full(len(self.eq_ids), np.nan)
        now = m.ltp[self.eq_ids, m.k]
        old = m.ltp[self.eq_ids, m.ago(15)]
        with np.errstate(divide="ignore", invalid="ignore"):
            return (self.eq_w / 100.0) * (now / old - 1.0) * N

    def _episode(self, now_s, z, d, m, fut_id, zi, S_d, conc):
        ep = self.episode
        fut_px = float(self.price(m, fut_id))
        if ep is None:
            if abs(z) >= config.ONSET_Z:
                self.episode = {
                    "id": int(now_s * 10), "t0": now_s, "dir": d, "fut0": fut_px,
                    "first": None, "first_t": None, "fut_cross_t": None, "stock_cross": {},
                    "type": "FORMING", "fired": set(), "iv0": None, "max_S": S_d,
                }
                self.quiet_since = None
            return
        if abs(z) < config.EPISODE_END_Z or (d != ep["dir"] and abs(z) >= config.ONSET_Z):
            if self.quiet_since is None:
                self.quiet_since = now_s
            if (now_s - self.quiet_since >= config.EPISODE_END_SEC) or (d != ep["dir"] and abs(z) >= 2.0):
                self.episode = None
                return
        else:
            self.quiet_since = None
        ep["max_S"] = max(ep["max_S"], S_d)
        if ep["fut_cross_t"] is None and abs(z) >= 2.0 and d == ep["dir"]:
            ep["fut_cross_t"] = now_s
        for j, sym in enumerate(self.eq_sym):
            if sym not in ep["stock_cross"] and np.isfinite(zi[j]) and zi[j] * ep["dir"] >= 2.0:
                ep["stock_cross"][sym] = now_s
                if ep["first"] is None:
                    ep["first"], ep["first_t"] = sym, now_s
        ft = ep["fut_cross_t"]
        if ep["stock_cross"]:
            t_first_stock = min(ep["stock_cross"].values())
            if ft is None or t_first_stock <= ft - 2.0:
                ep["type"] = "SINGLE-NAME" if (conc >= 0.6 and len(ep["stock_cross"]) == 1) else "BASKET-LED"
            elif ft is not None and t_first_stock >= ft + 2.0:
                ep["type"] = "FUTURES-LED"
            else:
                ep["type"] = "CO-FIRST"
        elif ft is not None:
            ep["type"] = "FUTURES-LED"

    def episode_view(self, now_s):
        ep = self.episode
        if not ep:
            return None
        return {"id": ep["id"], "age": now_s - ep["t0"], "dir": ep["dir"], "type": ep["type"],
                "first": ep["first"], "fut0": ep["fut0"], "n_cross": len(ep["stock_cross"]),
                "max_S": ep["max_S"]}


def _f(x):
    x = float(x)
    return x if math.isfinite(x) else None
