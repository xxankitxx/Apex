"""
SIMULATED feed — a synthetic Nifty session that exercises the whole system
end-to-end without a broker login (weekends, evenings, first runs).

It emits packets in Breeze's RAW layouts and pushes them through the same
`apply_packet` the live feed uses, so the engine, the dashboard and the paper
books cannot tell the difference. The market it makes is deliberately the one
the system is built to read:
  * a latent market factor plus noise for every heavyweight;
  * "episodes" every few minutes: BASKET-LED ones (heavyweights move first,
    Nifty futures catch up 3-8 s later — the domino lag), FUTURES-LED ones,
    and FAKE-OUTS that reverse; option sellers pull and IV rises as moves run;
  * a weekly chain with real-looking OI walls, VIX, previous closes.
The numbers are synthetic. A sim P&L says the plumbing works — NOTHING about edge.

Run via:  python run_apex.py sim [--speed 20] [--days 1] [--seed 7]
"""
import argparse
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta

import numpy as np

from . import config, greeks, universe
from .feed_breeze import write_chain
from .feed_core import HotStats, Recorder, Registry, apply_packet
from .table import Table

LOG = None


def log(msg):
    line = f"{datetime.now(config.IST).strftime('%H:%M:%S')} SIM {msg}"
    print(line, flush=True)
    try:
        LOG.write(line + "\n"); LOG.flush()
    except Exception:
        pass


STEP = 0.25                 # virtual seconds per simulation step
STOCK_PX = {"HDFCBANK": 1720, "ICICIBANK": 1380, "RELIANCE": 1460, "BHARTIARTL": 1950, "LT": 3800,
            "SBIN": 870, "AXISBANK": 1180, "INFY": 1530, "KOTAKBANK": 2150, "M&M": 3400, "TCS": 3100,
            "ITC": 410, "BAJFINANCE": 1010, "HINDUNILVR": 2500, "FEDERALBNK": 215, "INDUSINDBK": 760,
            "AUBANK": 780, "IDFCFIRSTB": 72, "BANKBARODA": 255, "SHRIRAMFIN": 640, "BSE": 2400,
            "BAJAJFINSV": 2050, "SBILIFE": 1850}
NIFTY0, BANK0, FIN0 = 25150.0, 56400.0, 26900.0


class Inst:
    __slots__ = ("id", "kind", "sym", "tok", "dtok", "px", "prev", "open", "hi", "lo", "ttq", "oi",
                 "bq", "aq", "bo", "ao", "spread", "strike", "rr", "exp", "beta", "vol", "lag_px", "tick",
                 "seg", "depth", "tbq", "tsq", "act")


class Sim:
    def __init__(self, table, speed, days, seed, record):
        self.t = table
        self.speed = speed
        self.days = days
        self.rng = np.random.default_rng(seed)
        random.seed(seed)
        self.record = record
        self.hot = HotStats(table)
        self.reg_version = 0
        self.tok_eq = 10000
        self.tok_fo = 50000

    # ── day setup ──────────────────────────────────────────────────────────
    def trading_days(self):
        d = config.now_ist().date()
        out = []
        while len(out) < self.days:
            if config.is_trading_day(d) and not (d == config.now_ist().date() and config.hm(config.now_ist()) >= 15 * 60):
                out.append(d)
            d += timedelta(days=1)
        return out

    def build(self, day):
        now = datetime(day.year, day.month, day.day, 9, 15, tzinfo=config.IST)
        self.w0, self.w1 = config.weekly_expiries(now, 2)
        self.reg = Registry()
        self.reg.version = self.reg_version
        self.insts = []
        self.by = {}
        self.t.rows[:] = np.zeros(config.MAX_ROWS, dtype=self.t.rows.dtype)
        r = self.rng
        self.nifty_prev = NIFTY0 * (1 + r.normal(0, 0.004))
        self.nifty = self.nifty_prev * (1 + r.normal(0, 0.003))     # opening gap
        self.fut_basis = self.nifty * 0.0035
        self.fut = self.nifty + self.fut_basis
        self.iv_base = float(r.uniform(0.105, 0.145))
        self.iv_bump = 0.0
        self.vix = self.iv_base * 100 * 1.05

        def mk(key, kind, sym, seg, px, prev, depth=False, **extra):
            it = Inst()
            if seg == "eq":
                self.tok_eq += 1; tok = self.tok_eq
            else:
                self.tok_fo += 1; tok = self.tok_fo
            it.kind, it.sym, it.seg, it.depth = kind, sym, seg, depth
            it.tok, it.dtok = f"4.1!{tok}", (f"4.2!{tok}" if depth else None)
            it.px, it.prev, it.open, it.hi, it.lo = px, prev, px, px, px
            it.ttq = 0.0; it.oi = 0.0; it.tbq = it.tsq = 0.0
            it.bq = np.full(5, 0.0); it.aq = np.full(5, 0.0)
            it.bo = np.full(5, 0.0); it.ao = np.full(5, 0.0)
            it.spread = 0.05; it.strike = extra.get("strike", 0.0); it.rr = extra.get("rr", "")
            it.exp = extra.get("expiry", ""); it.beta = 1.0; it.vol = 0.0; it.lag_px = px; it.tick = 0.05
            it.act = 1.0
            it.id = self.reg.add(key, kind, sym, it.tok, it.strike, extra.get("right", ""), it.exp,
                                 depth=depth, seg=seg, depth_token=it.dtok,
                                 **{k: v for k, v in extra.items() if k not in ("strike", "right", "expiry")})
            self.insts.append(it)
            self.by[key] = it
            return it

        mk("NIFTY|SPOT", "spot", "NIFTY", "eq", self.nifty, self.nifty_prev)
        f = mk("NIFTY|FUT", "fut", "NIFTY", "fo", self.fut, self.nifty_prev * 1.0035, depth=True)
        f.oi = 1.45e7; f.spread = 0.5
        mk("INDIAVIX|SPOT", "vix", "INDIAVIX", "eq", self.vix, self.vix)
        b = mk("BANKNIFTY|SPOT", "spot", "BANKNIFTY", "eq", BANK0, BANK0)
        mk("BANKNIFTY|FUT", "fut", "BANKNIFTY", "fo", BANK0 * 1.0035, BANK0 * 1.0035, depth=True).oi = 2.2e6
        mk("FINNIFTY|SPOT", "spot", "FINNIFTY", "eq", FIN0, FIN0)
        mk("FINNIFTY|FUT", "fut", "FINNIFTY", "fo", FIN0 * 1.0035, FIN0 * 1.0035).oi = 3.0e5
        self.stocks = []
        for sym, (wn, wb, wf, tag, grp) in universe.STOCKS.items():
            p0 = STOCK_PX.get(sym, 1000.0)
            prev = p0 * (1 + r.normal(0, 0.008))
            gap = (self.nifty / self.nifty_prev - 1) * r.uniform(0.6, 1.4)
            e = mk(f"{sym}|EQ", "eq", sym, "eq", prev * (1 + gap), prev, wn=wn, wb=wb, wf=wf, wtag=tag, group=grp)
            e.beta = float(r.uniform(0.7, 1.4)) * (1.25 if grp == "bank" else 1.0)
            e.vol = 0.00012 * float(r.uniform(0.8, 1.6))
            e.tick = 0.05 if e.px > 100 else 0.01
            e.spread = max(e.tick, round(e.px * 0.0002 / e.tick) * e.tick)
            e.act = float(r.uniform(0.6, 1.6))
            dep = sym in ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "RELIANCE")
            sf = mk(f"{sym}|FUT", "sfut", sym, "fo", e.px * 1.004, prev * 1.004, depth=dep,
                    wn=wn, wb=wb, wf=wf, group=grp)
            sf.oi = float(r.uniform(2e6, 6e7)) / max(e.px / 500, 1)
            sf.spread = e.spread * 2; sf.tick = e.tick
            self.stocks.append((e, sf, wn))
        # options
        self.center = round(self.nifty / config.STRIKE_STEP) * config.STRIKE_STEP
        self.extra_walls = {self.center + 50 * int(r.integers(3, 7)), self.center - 50 * int(r.integers(3, 7))}
        self.opts = []
        for wk, exp, band in ((0, self.w0, config.WEEKLY_BAND), (1, self.w1, config.NEXTWEEK_BAND)):
            for k in range(-band, band + 1):
                K = self.center + k * config.STRIKE_STEP
                for right, rr in (("call", "CE"), ("put", "PE")):
                    o = mk(f"NIFTY|OPT|{exp.isoformat()}|{int(K)}|{rr}", "opt", "NIFTY", "fo", 0.0, 0.0,
                           depth=(wk == 0 and abs(k) <= config.HERO_BAND + 1),
                           strike=K, right=right, expiry=exp.isoformat(), rr=rr, week=wk)
                    o.oi = self.base_oi(K, rr) * (0.35 if wk else 1.0)
                    self.opts.append(o)
        self.reg.save(self.t)
        self.reg_version = self.reg.version
        self.by_token = self.reg.by_token
        self.rec = Recorder(day.isoformat(), enabled=self.record, suffix="_sim")
        # previous closes for options = model price at yesterday's level
        now0 = datetime(day.year, day.month, day.day, 9, 15, tzinfo=config.IST)
        for o in self.opts:
            T = greeks.years_to_expiry(o.exp, now0 - timedelta(days=1))
            o.prev = float(greeks.b76_price(self.nifty_prev * 1.0005, o.strike, T, self.iv_base + 0.005, o.rr == "CE"))
        self.ep = None
        self.next_ep = 9 * 3600 + 15 * 60 + float(r.uniform(240, 600))
        self.factor = 0.0
        self.latent = 0.0          # basket-implied cumulative log move driving stocks
        self.fut_lagged = 0.0
        log(f"{day} built: {len(self.insts)} instruments · weekly {self.w0} · next {self.w1} · "
            f"Nifty {self.nifty:.1f} (prev {self.nifty_prev:.1f}) · IV {self.iv_base*100:.1f}")

    def base_oi(self, K, rr):
        r = self.rng
        d = (K - self.center) / config.STRIKE_STEP
        base = 4.0e6 * math.exp(-abs(d) / 9.0)
        # walls: round thousands/500s and a couple of random strikes
        if K % 500 == 0 or K in self.extra_walls:
            base *= 3.5
        if (rr == "CE" and d > 0) or (rr == "PE" and d < 0):
            base *= 1.4
        return float(base * r.uniform(0.6, 1.2))

    # ── episodes: the domino ───────────────────────────────────────────────
    def maybe_episode(self, tsec):
        r = self.rng
        if self.ep is None and tsec >= self.next_ep:
            kind = r.choice(["BASKET", "BASKET", "BASKET", "FUTURES", "FAKE"])
            d = 1 if r.random() < 0.5 else -1
            dur = float(r.uniform(50, 200))
            size = float(r.uniform(18, 70)) * (0.5 if kind == "FAKE" else 1.0)      # Nifty points
            self.ep = {"kind": kind, "dir": d, "t0": tsec, "dur": dur, "size": size,
                       "lag": float(r.uniform(3, 8)), "lead": set(r.choice(len(self.stocks), size=6, replace=False))}
            self.next_ep = tsec + dur + float(r.uniform(180, 900))
        if self.ep and tsec > self.ep["t0"] + self.ep["dur"] + 60:
            self.ep = None

    def ep_drift(self, tsec):
        """Per-second drift in Nifty points for (basket, futures) at time tsec."""
        e = self.ep
        if not e:
            return 0.0, 0.0
        u = tsec - e["t0"]
        if u < 0 or u > e["dur"]:
            return 0.0, 0.0
        rate = e["size"] / e["dur"] * 2.2 * math.exp(-u / (e["dur"] * 0.6))
        if e["kind"] == "FAKE" and u > e["dur"] * 0.35:
            rate = -rate * 1.4
        rate *= e["dir"]
        if e["kind"] == "FUTURES":
            return rate * 0.3, rate
        return rate, 0.0

    # ── the step ───────────────────────────────────────────────────────────
    def step(self, tsec, now_dt, vns):
        r = self.rng
        self.maybe_episode(tsec)
        basket_drift, fut_extra = self.ep_drift(tsec)
        noise = float(r.normal(0, 0.55))                        # Nifty pts per step, market factor
        self.factor += noise * 0.6
        lead_move = basket_drift * STEP                          # Nifty points this step
        # stocks: beta x factor + lead names get the episode first
        nifty_move_from_stocks = 0.0
        in_ep = self.ep is not None
        for j, (e, sf, wn) in enumerate(self.stocks):
            pts = noise * 0.6 * e.beta + (lead_move * (1.6 if (in_ep and j in self.ep["lead"]) else 0.7))
            ret = pts / self.nifty + float(r.normal(0, e.vol))
            e.px = max(e.px * (1 + ret), e.tick)
            sf.px = e.px * (1.004 - 0.0001 * (tsec - 33300) / 22500)
            if wn > 0:
                nifty_move_from_stocks += wn / 100 * ret * self.nifty
        other = 0.33 * (noise * 0.6 + lead_move * 0.7)          # names we don't track
        self.nifty += nifty_move_from_stocks + other + float(r.normal(0, 0.15))
        # futures: follows the basket with a lag (the domino), plus its own episode drift
        fair = self.nifty + self.fut_basis * max(0.2, 1 - (tsec - 33300) / 400000)
        lag = self.ep["lag"] if self.ep else 4.0
        a = 1 - math.exp(-STEP / lag)
        self.fut += a * (fair - self.fut) + fut_extra * STEP + float(r.normal(0, 0.25))
        if fut_extra:
            self.nifty += fut_extra * STEP * 0.9
        # IV: rises while a move runs, mean-reverts otherwise
        speed = abs(basket_drift) + abs(fut_extra)
        self.iv_bump += (0.0009 * speed * STEP) - self.iv_bump * STEP / 240
        iv = self.iv_base + self.iv_bump
        self.vix = iv * 100 * 1.05
        # emit
        T0 = greeks.years_to_expiry(self.w0.isoformat(), now_dt)
        T1 = greeks.years_to_expiry(self.w1.isoformat(), now_dt)
        F0 = self.fut - self.fut_basis * 0.6
        ks = np.array([o.strike for o in self.opts])
        isc = np.array([o.rr == "CE" for o in self.opts])
        Ts = np.array([T0 if o.exp == self.w0.isoformat() else T1 for o in self.opts])
        mny = (ks - F0) / F0
        skew = iv + np.where(isc, -0.08, 0.12) * mny * 10 * 0.1 + 0.6 * mny * mny * 100 * 0.01
        prices = np.empty(len(self.opts))
        for T in (T0, T1):
            m = Ts == T
            prices[m] = greeks.b76_price(F0, ks[m], T, skew[m], isc[m])
        d = self.ep["dir"] if (self.ep and speed > 0.2) else 0
        self.emit_simple(self.by["NIFTY|SPOT"], self.nifty, vns, now_dt, volume=False)
        self.emit_simple(self.by["INDIAVIX|SPOT"], self.vix, vns, now_dt, volume=False, every=4)
        bn = self.by["BANKNIFTY|SPOT"]; bn_ret = sum(wb / 100 * (e.px / e.prev - 1) for e, sf, wn in self.stocks
                                                     for wb in [universe.STOCKS[e.sym][1]] if wb)
        self.emit_simple(bn, BANK0 * (1 + bn_ret), vns, now_dt, volume=False, every=2)
        self.emit_book(self.by["BANKNIFTY|FUT"], BANK0 * (1 + bn_ret) * 1.0035, vns, now_dt, d, 30, every=2)
        fn = self.by["FINNIFTY|SPOT"]; fn_ret = sum(wf / 100 * (e.px / e.prev - 1) for e, sf, wn in self.stocks
                                                    for wf in [universe.STOCKS[e.sym][2]] if wf)
        self.emit_simple(fn, FIN0 * (1 + fn_ret), vns, now_dt, volume=False, every=4)
        self.emit_book(self.by["FINNIFTY|FUT"], FIN0 * (1 + fn_ret) * 1.0035, vns, now_dt, d, 65, every=4)
        self.emit_book(self.by["NIFTY|FUT"], self.fut, vns, now_dt, d * (1 if fut_extra or self.ep else 0), 75 * 4)
        for j, (e, sf, wn) in enumerate(self.stocks):
            lead = in_ep and j in self.ep["lead"]
            dd = d if (lead or speed > 1.0) else 0
            if lead or r.random() < 0.55:
                self.emit_book(e, e.px, vns, now_dt, dd, int(200 * e.act), eq=True)
            if r.random() < 0.35:
                self.emit_book(sf, sf.px, vns, now_dt, dd, int(300 * e.act))
        for o, px in zip(self.opts, prices):
            px = max(round(px / 0.05) * 0.05, 0.05)
            near = abs(o.strike - F0) <= 3 * config.STRIKE_STEP and o.exp == self.w0.isoformat()
            if not near and r.random() > 0.4:
                continue
            od = 0
            if d:
                od = d if o.rr == "CE" else -d
            o.oi = max(o.oi + float(r.normal(0, 600)) + (1500 if (od < 0) else 0), 0)
            self.emit_book(o, px, vns, now_dt, od, 65 * (40 if near else 8), opt=True)

    def emit_simple(self, it, px, vns, now_dt, volume=True, every=1):
        if every > 1 and self.rng.random() > 1.0 / every:
            return
        it.px = px
        it.hi, it.lo = max(it.hi, px), min(it.lo, px)
        pkt = [it.tok, it.open, round(px, 2), it.hi, it.lo, round((px / it.prev - 1) * 100, 2) if it.prev else 0,
               0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "", 0, 0, int(vns // 1e9), it.prev]
        self.push(pkt, vns)

    def emit_book(self, it, px, vns, now_dt, d, lot, eq=False, opt=False, every=1):
        """Quote (+depth) for a tradable instrument. d = +1 means buyers are
        aggressive and sellers thin out (the instrument should rise)."""
        r = self.rng
        if every > 1 and r.random() > 1.0 / every:
            return
        tick = 0.05 if opt else it.tick
        old = it.px
        if opt and old > 0 and abs(px - old) < tick / 2:
            px = old
        it.px = px
        if it.open == 0:
            it.open = it.hi = it.lo = px
        it.hi, it.lo = max(it.hi, px), min(it.lo, px)
        spr = max(tick, round((0.05 + px * 0.0015) / tick) * tick) if opt else max(tick, it.spread)
        px = float(px)
        bid = round((px - spr / 2) / tick) * tick
        ask = max(bid + tick, round((px + spr / 2) / tick) * tick)
        # trades
        q = float(r.poisson(2.0 + 6.0 * abs(d))) * lot / (5 if eq else 1)
        if d > 0:
            last = ask
        elif d < 0:
            last = bid
        else:
            last = ask if px >= old else bid
        it.ttq += q
        # standing quantities: the side being run over thins, the other refills
        base = lot * 12
        thin = 0.35 if d else 1.0
        fb = 1.6 if d > 0 else (thin if d < 0 else 1.0)
        fa = 1.6 if d < 0 else (thin if d > 0 else 1.0)
        rnd = random.random
        bq = [round(base * (0.6 + 0.8 * rnd()) * fb / lot) * lot + lot for _ in range(5)]
        aq = [round(base * (0.6 + 0.8 * rnd()) * fa / lot) * lot + lot for _ in range(5)]
        bo = [max(1, round(x / (lot * (2 + 4 * rnd())))) for x in bq]
        ao = [max(1, round(x / (lot * (2 + 4 * rnd())))) for x in aq]
        it.tbq = float(sum(bq) * 8); it.tsq = float(sum(aq) * 8)
        ltt = int(vns // 1e9)
        chg = round((last / it.prev - 1) * 100, 2) if it.prev else 0
        if it.seg == "fo":
            pkt = [it.tok, it.open, round(last, 2), it.hi, it.lo, chg, round(bid, 2), float(bq[0]), round(ask, 2),
                   float(aq[0]), q, round((it.hi + it.lo + last) / 3, 2), it.oi, 0, it.ttq, it.tbq, it.tsq,
                   it.ttq * last, "", 0, 0, ltt, it.prev]
        else:
            pkt = [it.tok, it.open, round(last, 2), it.hi, it.lo, chg, round(bid, 2), float(bq[0]), round(ask, 2),
                   float(aq[0]), q, round((it.hi + it.lo + last) / 3, 2), it.ttq, it.tbq, it.tsq,
                   it.ttq * last, "", 0, 0, ltt, it.prev]
        self.push(pkt, vns)
        if it.dtok:
            lv = []
            for k in range(5):
                lv.append([round(bid - k * tick, 2), float(bq[k]), float(bo[k]), "N",
                           round(ask + k * tick, 2), float(aq[k]), float(ao[k]), "N"])
            self.push([it.dtok, ltt, lv], vns)

    def push(self, pkt, vns):
        t0 = time.perf_counter_ns()
        apply_packet(self.t, self.by_token, pkt, vns)
        self.rec.put("p", vns, pkt)
        self.hot.add((time.perf_counter_ns() - t0) / 1000.0)

    def chain(self, vns):
        out = {}
        for o in self.opts:
            if o.exp != self.w0.isoformat():
                continue
            out.setdefault(str(int(o.strike)), {})["call" if o.rr == "CE" else "put"] = o.oi
        payload = {"expiry": self.w0.isoformat(), "oi": out}
        write_chain(self.t, payload)
        self.rec.put("chain", vns, payload)

    # ── run ────────────────────────────────────────────────────────────────
    def run(self):
        self.t.set("speed", self.speed)
        self.t.set("feed_state", 5)
        for n, day in enumerate(self.trading_days()):
            t_open = datetime(day.year, day.month, day.day, 9, 15, tzinfo=config.IST)
            self.vns = int(t_open.timestamp() * 1e9)
            self.t.set("now_ns", self.vns)
            self.build(day)
            self.rec.put("reg", self.vns, self.reg.items)
            self.chain(self.vns)
            tsec = 9 * 3600 + 15 * 60
            end = 15 * 3600 + 30 * 60
            last_chain = tsec
            real0 = time.perf_counter()
            v0 = tsec
            while tsec < end and not int(self.t.c("stop")):
                tsec += STEP
                self.vns = int((t_open.timestamp() + tsec - (9 * 3600 + 15 * 60)) * 1e9)
                self.t.set("now_ns", self.vns)
                now_dt = datetime.fromtimestamp(self.vns / 1e9, config.IST)
                self.step(tsec, now_dt, self.vns)
                if tsec - last_chain >= config.CHAIN_POLL_S:
                    last_chain = tsec
                    self.chain(self.vns)
                self.t.set("vix", self.vix); self.t.set("vix_ns", self.vns)
                self.t.set("feed_hb_ns", time.time_ns())
                sp = max(float(self.t.c("speed")), 0.1)
                due = real0 + (tsec - v0) / sp
                lag = due - time.perf_counter()
                if lag > 0:
                    time.sleep(lag)
                elif lag < -2.0:              # can't keep up at this speed: rebase, don't spiral
                    real0, v0 = time.perf_counter(), tsec
            # hold the close for a moment so the engine sees 15:30 and flattens
            for _ in range(8):
                tsec += STEP * 4
                self.vns = int((t_open.timestamp() + tsec - (9 * 3600 + 15 * 60)) * 1e9)
                self.t.set("now_ns", self.vns)
                time.sleep(0.25)
            self.rec.stop()
            log(f"{day} session finished")
            if int(self.t.c("stop")):
                break
        self.t.set("feed_state", 7)
        log("simulation complete")


def main():
    global LOG
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the supervisor's: it sets ctrl.stop
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    LOG = open(os.path.join(config.LOG_DIR, "sim.log"), "a", encoding="utf-8")
    Sim(Table(), a.speed, a.days, a.seed, a.record).run()


if __name__ == "__main__":
    main()
