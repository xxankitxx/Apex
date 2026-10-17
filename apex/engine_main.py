"""
ENGINE process — everything that thinks, isolated from the tick path.

Every 100 ms of system time (wall clock live; virtual clock in sim/replay):
  sample the shared table -> buyers/sellers flow -> Greeks (4 Hz) -> pressure
  zones (on new chain) -> domino/basket + episode -> force detector ->
  advisors -> every variant's paper book (exits, then entries)
Every 250 ms: publish the full state for the dashboard.
At the close (or a date change): save books, write the trades CSV, record the
day for learning, run the learning loop, start the new day with its decisions.
"""
import json
import math
import os
import sys
import time
import traceback
from collections import deque
from datetime import datetime

import numpy as np

from . import audio, config, greeks
from .engine import learning, paper
from .engine.extras import BankLead, EpisodeLog, LagMeter, Straddle, event_today
from .engine.straddle_watch import StraddleWatch
from .engine.gex import GexMap
from .engine.domino import Domino
from .engine.flow import CLS, REFILL, Flow
from .engine.levels import Force, Pressure
from .engine.market import Market
from .feed_core import Registry
from .table import StateBlob, Table, clean, FEED_STATES

LOG = None


def log(msg):
    line = f"{datetime.now(config.IST).strftime('%H:%M:%S')} ENGINE {msg}"
    print(line, flush=True)
    try:
        LOG.write(line + "\n"); LOG.flush()
    except Exception:
        pass


def fnum(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


class Engine:
    def __init__(self, table: Table, blob: StateBlob, mode: str):
        self.t, self.blob, self.mode = table, blob, mode
        self.m = Market()
        self.flow = Flow(config.MAX_ROWS)
        self.pressure = Pressure()
        self.gex = GexMap()
        self.force = Force()
        self.reg_version = -1
        self.items = []
        self.domino = None
        self.events = deque(maxlen=120)
        self.greek = {}                      # row id -> dict(iv, delta, theta_min, vega)
        self.iv_hist = deque(maxlen=900)     # (t, atm_iv) at 1 Hz
        self.oi_hist = deque(maxlen=400)     # (t, {id: oi}) at 1 Hz (heroes + futures)
        self.last_greeks = self.last_publish = self.last_1hz = 0.0
        self.day = None
        self.books = {}
        self.lstate = learning.load_state()
        self.last_reason = ""
        self.loop_ms = 0.0
        self.advisors = {}
        self.ctx = {}
        self.straddle = Straddle()
        self.watch = StraddleWatch()          # fixed-strike straddle: spikes, gamma leg, ATM rolls
        self._watch_err = 0.0
        self.bank = BankLead()
        self.lag = LagMeter()
        self.eplog = None

    # ── registry ───────────────────────────────────────────────────────────
    def load_registry(self):
        v = int(self.t.c("reg_version"))
        if v == self.reg_version or v <= 0:
            return
        reg = Registry.load()
        self.reg_version = v
        old_key = getattr(self, "key", {})
        self.items = reg["items"]
        self.key = {it["key"]: it["id"] for it in self.items}
        moved = any(old_key.get(k) not in (None, i) for k, i in self.key.items())
        if moved:                                   # a feed restart re-numbered rows: history is void
            log("instrument ids changed — resetting price history")
            self.m = Market()
            self.flow = Flow(config.MAX_ROWS)
            self.greek = {}
            self.iv_hist.clear(); self.oi_hist.clear()
        self.opts = [it for it in self.items if it["kind"] == "opt"]
        self.fut_id = self.key.get("NIFTY|FUT")
        self.spot_id = self.key.get("NIFTY|SPOT")
        self.bn_id = self.key.get("BANKNIFTY|FUT") or self.key.get("BANKNIFTY|SPOT")
        if self.domino is None:
            self.domino = Domino(self.items, config.MAX_ROWS)
        else:
            self.domino.reload(self.items, config.MAX_ROWS)
        exps = sorted({it["expiry"] for it in self.opts})
        self.w0 = exps[0] if exps else ""
        self.w1 = exps[1] if len(exps) > 1 else ""
        log(f"registry v{v}: {len(self.items)} instruments, weekly {self.w0}, next {self.w1}")

    # ── day lifecycle ──────────────────────────────────────────────────────
    def start_day(self, day):
        self.day = day
        self.armed_ep = None
        self.eplog = EpisodeLog(day)
        self.lag = LagMeter()
        self.straddle = Straddle()
        if getattr(self, "watch", None) is not None:
            self.watch.close()
        self.watch = StraddleWatch(day)
        self.lstate = learning.load_state()
        loaded = paper.load_books(day)
        champ = self.lstate["champion"]
        books = {}
        for name, params in config.VARIANTS.items():
            books[name] = (loaded or {}).get(name) or paper.Book(name, params, day)
        books["RAW"] = (loaded or {}).get("RAW") or paper.Book("RAW", config.VARIANTS[champ], day)
        self.books = books
        self.champion = champ
        self.gates = list(self.lstate.get("gates", []))
        self.ev("SYSTEM", f"day {day} · champion {champ} · gates {', '.join(self.gates) or 'none'} · "
                          f"capital ₹{books[champ].capital:,.0f}")

    def end_day(self):
        if not self.books or getattr(self, "_learned", "") == self.day:
            return
        self._learned = self.day
        if learning.already_learned(self.day):
            log(f"day {self.day} was already learned — not repeating")
            return
        paper.save_books(self.books, self.day)
        paper.write_trades_csv(self.books[self.champion], self.day)
        learning.record_day(self.day, self.books)
        s = learning.learn(self.day)
        self.ev("LEARN", f"{self.day}: champion next session {s['champion']}, gates "
                         f"{', '.join(s['gates']) or 'none'}, status {s.get('status')}")
        if s.get("log") and s["log"][-1].get("day") == self.day:
            audio.play("learn")
        log(f"day {self.day} closed and learned")

    def ev(self, kind, text):
        self.events.appendleft({"t": self.now_dt.strftime("%H:%M:%S") if hasattr(self, "now_dt") else "",
                                "k": kind, "x": text})

    # ── main step ──────────────────────────────────────────────────────────
    def step(self):
        now_ns = self.t.now_ns()
        now_s = now_ns / 1e9
        self.now_s = now_s
        self.now_dt = datetime.fromtimestamp(now_s, config.IST)
        day = self.now_dt.date().isoformat()
        if self.day is None:
            self.start_day(day)
        elif day != self.day:
            self.end_day()
            self.start_day(day)
        elif config.hm(self.now_dt) >= config.mins((15, 31)):
            self.end_day()

        snap = self.t.snapshot()
        dt = now_s - self.m.now if self.m.now else 0.1
        self.m.push(snap, now_s)
        if dt > 0:
            self.flow.update(self.m, dt)
        spot = self.px(self.spot_id)
        fut = self.px(self.fut_id)
        if not np.isfinite(fut):
            fut = spot
        if now_s - self.last_greeks >= 0.25:
            self.last_greeks = now_s
            self.compute_greeks(spot, fut)
        if now_s - self.last_1hz >= 1.0:
            self.last_1hz = now_s
            self.iv_hist.append((now_s, self.atm_iv))
            self.oi_hist.append((now_s, {it["id"]: float(snap["oi"][it["id"]])
                                         for it in self.items if it["kind"] in ("opt", "fut", "sfut")}))
        self.pressure.refresh(self.t, spot)
        self.update_gex(fut)
        self.domino.update(self.m, now_s)
        dom = self.domino.state
        ep = self.domino.episode
        if ep is not None and ep.get("iv0") is None and self.atm_iv:
            ep["iv0"] = self.atm_iv
        K_up, K_dn = self.coherence()
        d = dom.get("dir", 1)
        self.straddle.update(self.m, snap, self.key, getattr(self, "atm", None), self.w0, now_s)
        try:
            self.update_watch(snap, now_s, float(fut) if np.isfinite(fut) else None)
        except Exception:                        # the watch is an observer: never let it stop the loop
            if now_s - self._watch_err > 60:
                self._watch_err = now_s
                log("straddle watch: " + traceback.format_exc().strip().splitlines()[-1])
        self.bank.update(self.m, self.bn_id, now_s, self.domino.episode_view(now_s))
        self.lag.update(ep)
        self.force.update(self.m, self.flow, self.fut_id, spot, self.pressure,
                          K_up if d > 0 else K_dn, now_s)
        if not np.isfinite(fut):
            return
        self.ctx = ctx = {
            "now_s": now_s, "now_dt": self.now_dt, "fut": float(fut), "spot": float(spot) if np.isfinite(spot) else None,
            "domino": dom, "episode": self.domino.episode_view(now_s), "w0": self.w0,
            "options": self.option_rows(snap), "advisors": {}, "K_up": K_up, "K_dn": K_dn,
            "iv_rise_since_onset": (self.atm_iv - ep["iv0"]) * 100 if (ep and ep.get("iv0") and self.atm_iv) else None,
        }
        ctx["by_id"] = {o["id"]: o for o in ctx["options"]}
        ctx["by_key"] = {o["key"]: o for o in ctx["options"]}
        ctx["book_state"] = self.book_state()
        ctx["straddle_watch"] = self.watch.view(series=False)
        for kind, text in self.watch.drain_events():
            self.ev(kind, text)
            if kind == "SPIKE":
                audio.play("armed", now_s, min_gap_s=60.0)     # the same "look up" chime as the Triangle
        if ctx["episode"]:
            ctx["advisors"] = self.advise(ctx, ctx["episode"]["dir"])
        self.advisors = ctx["advisors"]
        self.maybe_arm(ctx)
        self.run_books(ctx)
        if self.eplog:
            self.eplog.update(ctx, self)

    def book_state(self):
        """Opposing-side classes for every hero contract (used by the book exit and the book advisor)."""
        out = {}
        for i, rr, _ in self.heroes():
            d = 1 if rr == "CE" else -1
            cq, co, imb = self.flow.side(i, d)
            out[i] = {"opp_q": cq, "opp_o": co, "imb": imb, "lead": float(self.flow.lead[i])}
        return out

    def maybe_arm(self, ctx):
        """The 'look up' chime: every corner of the Triangle past 80 %, once per episode."""
        ep, dom = ctx.get("episode"), ctx.get("domino") or {}
        champ = self.books.get(self.champion)
        if not ep or not champ or champ.pos or ep["id"] == getattr(self, "armed_ep", None):
            return
        hmn = config.hm(ctx["now_dt"])
        if hmn < config.mins(config.SUPPRESS_UNTIL) or hmn >= config.mins(config.LAST_ENTRY):
            return                                  # the trigger itself can't fire here either
        d = ep["dir"]
        push = (dom.get("z", 0.0) * d) / champ.p["m_star"]
        crowd = (dom.get("S_up", 0.0) if d > 0 else dom.get("S_dn", 0.0)) / champ.p["s_star"]
        late = self.lateness(ctx)
        if push >= 0.8 and crowd >= 0.8 and late is not None and late < 0.8:
            self.armed_ep = ep["id"]
            audio.play("armed", ctx["now_s"], min_gap_s=20.0)
            self.ev("ARMED", f"Triangle closing: push {push:.0%}, together {crowd:.0%}, "
                             f"{(1 - late):.0%} room left — {'CE' if d > 0 else 'PE'} side")

    def px(self, i):
        if i is None:
            return np.nan
        return float(self.m.ltp[i, self.m.k])

    # ── Greeks ─────────────────────────────────────────────────────────────
    def compute_greeks(self, spot, fut):
        self.atm_iv = getattr(self, "atm_iv", None)
        ref = spot if np.isfinite(spot) else fut
        if not np.isfinite(ref):
            return
        snap = self.m.snap
        for exp in (self.w0, self.w1):
            rows = [it for it in self.opts if it["expiry"] == exp]
            if not rows:
                continue
            ids = np.array([it["id"] for it in rows])
            K = np.array([it["strike"] for it in rows])
            is_call = np.array([it["right"] == "call" for it in rows])
            bid, ask, ltp = snap["bid"][ids], snap["ask"][ids], snap["ltp"][ids]
            mid = np.where((bid > 0) & (ask > 0) & (ask >= bid), (bid + ask) / 2, ltp)
            mid = np.where(mid > 0, mid, np.nan)
            strikes = sorted(set(K))
            ce = [np.nanmean(mid[(K == k) & is_call]) if ((K == k) & is_call).any() else np.nan for k in strikes]
            pe = [np.nanmean(mid[(K == k) & ~is_call]) if ((K == k) & ~is_call).any() else np.nan for k in strikes]
            F = greeks.synthetic_forward(strikes, ce, pe, ref)
            T = greeks.years_to_expiry(exp, self.now_dt)
            iv = greeks.implied_vol(mid, F, K, T, is_call)
            g = greeks.greeks(F, K, T, iv, is_call)
            for j, i in enumerate(ids):
                self.greek[int(i)] = {"iv": fnum(iv[j] * 100, 2), "delta": fnum(g["delta"][j], 3),
                                      "theta_min": fnum(g["theta_min"][j], 4), "vega": fnum(g["vega"][j], 2),
                                      "gamma": fnum(g["gamma"][j], 5)}
            if exp == self.w0:
                atm = min(strikes, key=lambda k: abs(k - F))
                sel = (K == atm)
                v = iv[sel]
                v = v[np.isfinite(v)]
                self.atm_iv = float(v.mean()) if v.size else self.atm_iv
                self.fwd = F
                self.atm = atm

    def option_rows(self, snap):
        now_ns = self.t.now_ns()
        out = []
        for it in self.opts:
            i = it["id"]
            g = self.greek.get(i, {})
            ltp = float(snap["ltp"][i])
            rn = int(snap["recv_ns"][i])
            out.append({"id": i, "key": it["key"], "strike": it["strike"], "rr": it.get("rr"),
                        "week": it.get("week", 0), "expiry": it["expiry"],
                        "ltp": ltp if ltp > 0 else None,
                        "bid": fnum(snap["bid"][i]), "ask": fnum(snap["ask"][i]),
                        "delta": g.get("delta"), "iv": g.get("iv"),
                        "age": (now_ns - rn) / 1e9 if rn else 9e9})
        return out

    # ── coherence across the ten hero contracts ────────────────────────────
    def heroes(self):
        atm = getattr(self, "atm", None)
        if atm is None:
            return []
        hs = []
        for k in range(-config.HERO_BAND, config.HERO_BAND + 1):
            for rr in ("CE", "PE"):
                i = self.key.get(f"NIFTY|OPT|{self.w0}|{int(atm + k * config.STRIKE_STEP)}|{rr}")
                if i is not None:
                    hs.append((i, rr, atm + k * config.STRIKE_STEP))
        return hs

    def coherence(self):
        hs = self.heroes()
        if not hs:
            return 0.0, 0.0
        up = [self.flow.run_score(i, 1 if rr == "CE" else -1, self.m) for i, rr, _ in hs]
        dn = [self.flow.run_score(i, -1 if rr == "CE" else 1, self.m) for i, rr, _ in hs]
        return (float(np.mean([x >= 0.3 for x in up])), float(np.mean([x >= 0.3 for x in dn])))

    # ── advisors: would-have verdicts (D-033) ──────────────────────────────
    def advise(self, ctx, d):
        a = {}
        iv5 = self.iv_change(300)
        a["iv_late"] = {"veto": bool(iv5 is not None and self.atm_iv and iv5 >= 0.08 * self.atm_iv * 100),
                        "why": f"ATM IV {iv5:+.2f} pts in 5 min" if iv5 is not None else "IV history warming"}
        dest = self.pressure.destination(ctx["spot"] or ctx["fut"], d)
        opt, _ = paper.choose_contract(ctx, d)
        need = None
        if opt and opt.get("delta"):
            th = abs((self.greek.get(opt["id"], {}) or {}).get("theta_min") or 0.0)
            need = (12.0 + th * 5) / max(abs(opt["delta"]), 0.05)
        a["room"] = {"veto": bool(dest and need and dest["room"] < 1.3 * need),
                     "why": (f"next wall {dest['level']:.0f} is {dest['room']:.0f} pts away, need ~{need:.0f}"
                             if dest and need else "no wall data")}
        K = ctx["K_up"] if d > 0 else ctx["K_dn"]
        a["coherence"] = {"veto": K < 0.5, "why": f"{K:.0%} of hero contracts confirm"}
        fv = self.force.view()
        a["force"] = {"veto": bool(fv.get("dir") == d and fv["verdict"] == "HOLD-STRONG"),
                      "why": f"futures level {fv.get('name', '—')}: {fv['verdict']}"}
        et = ctx["episode"]["type"]
        a["episode"] = {"veto": et in ("FUTURES-LED", "SINGLE-NAME"), "why": f"episode {et}"}
        # book: on the contract we would buy, are the opposing orders refilling or is the book against us?
        if opt:
            bk = ctx["book_state"].get(opt["id"]) or {}
            refill = bk.get("opp_q") == REFILL or bk.get("opp_o") == REFILL
            against = bk.get("imb", 0.0) < -0.3
            a["book"] = {"veto": bool(refill or against),
                         "why": (f"{opt['strike']:.0f} {opt['rr']}: sellers qty {CLS[bk.get('opp_q', 0)]}, "
                                 f"orders {CLS[bk.get('opp_o', 0)]}, order imbalance {bk.get('imb', 0.0):+.2f}, "
                                 f"book leads price {bk.get('lead', 0.0):+.2f}")}
        else:
            a["book"] = {"veto": False, "why": "no contract in band"}
        sv = self.straddle.view()
        a["premium"] = {"veto": self.straddle.veto(),
                        "why": (f"ATM straddle {sv['px']:.1f} vs VWAP {sv['vwap']:.1f}: {sv['state']}"
                                if sv["vwap"] else "straddle VWAP warming")}
        sig = (self.domino.state or {}).get("sigma15") or 0.0
        a["quiet"] = {"veto": bool(sig and sig < 2.5 and self.straddle.veto()),
                      "why": f"σ15 {sig:.1f} pts, premium {sv['state'].lower()}"}
        a["bank"] = {"veto": self.bank.veto(d), "why": f"Bank Nifty futures z {self.bank.z:+.1f}"}
        evt = event_today(self.day)
        a["event"] = {"veto": bool(evt), "why": evt or "no event today"}
        gv, gw = self.watch.advise(d)
        a["gamma_leg"] = {"veto": bool(gv), "why": gw}
        xv, xw = self.gex.advise(d, ctx["fut"])
        a["gex_room"] = {"veto": bool(xv), "why": xw}
        return a

    # ── dealer gamma map (D-062): an observer, never allowed to stop the loop ──
    def update_gex(self, fut):
        try:
            atm_iv = getattr(self, "atm_iv", None)
            if not self.pressure.oi or not self.pressure.expiry or not atm_iv or not getattr(self, "opts", None):
                return
            iv_k = {}
            for it in self.opts:
                if it["expiry"] != self.w0:
                    continue
                v = (self.greek.get(it["id"]) or {}).get("iv")
                if v:
                    iv_k.setdefault(float(it["strike"]), []).append(v / 100.0)
            iv_k = {k: float(np.mean(v)) for k, v in iv_k.items()}
            F = getattr(self, "fwd", None) or (float(fut) if np.isfinite(fut) else None)
            self.gex.update(self.pressure.version, self.pressure.oi, self.pressure.expiry,
                            self.now_dt, F, iv_k, atm_iv)
        except Exception:
            if time.time() - getattr(self, "_gex_err", 0) > 60:
                self._gex_err = time.time()
                log("gex map: " + traceback.format_exc().strip().splitlines()[-1])

    # ── the fixed-strike straddle watch ────────────────────────────────────
    def _leg_quotes(self, snap, k):
        """(quote, greeks, ids) for strike k's CE and PE, or (None, None, None) if either is missing."""
        quote, g, ids = {}, {}, []
        for rr in ("CE", "PE"):
            i = self.key.get(f"NIFTY|OPT|{self.w0}|{int(k)}|{rr}")
            if i is None:
                return None, None, None
            quote[rr] = (float(snap["ltp"][i]), float(snap["bid"][i]), float(snap["ask"][i]))
            g[rr] = self.greek.get(i, {})
            ids.append(i)
        return quote, g, ids

    def update_watch(self, snap, now_s, fut):
        atm = getattr(self, "atm", None)
        if atm is None or not self.w0:
            return
        w = self.watch
        roll = w.wants_roll()
        if roll is not None:
            quote, _, _ = self._leg_quotes(snap, roll)
            if quote:
                w.roll(now_s, self.now_dt, roll, quote)
            else:
                w._roll_to = None
        K = w.K if w.K is not None else atm
        quote, g, ids = self._leg_quotes(snap, K)
        if quote is None:
            return
        vol = 0.0
        if self.m.prev_snap is not None:
            for i in ids:
                dv = float(snap["ttq"][i]) - float(self.m.prev_snap["ttq"][i])
                if dv == dv and dv > 0:
                    vol += dv
        w.update(now_s, self.now_dt, atm, quote, g, fut, vol)

    def fut_book(self):
        i = self.fut_id
        if i is None:
            return None
        f = self.flow
        return {"imb_q": fnum(f.imb_q[i], 2), "imb_o": fnum(f.imb_o[i], 2), "imb_t": fnum(f.imb_t[i], 2),
                "imb_t_chg": fnum(f.imb_t_chg[i], 2), "lead": fnum(f.lead[i], 2),
                "bid_cls": CLS[int(f.cls_b[i])], "ask_cls": CLS[int(f.cls_s[i])],
                "bid_ord_cls": CLS[int(f.cls_bo[i])], "ask_ord_cls": CLS[int(f.cls_so[i])],
                "sbo": fnum(self.m.sbo[i, self.m.k], 0), "sso": fnum(self.m.sso[i, self.m.k], 0)}

    def lateness(self, ctx):
        """Fraction of the not-late allowance already used (0 fresh .. 1 late) for the champion."""
        ep = self.domino.episode if self.domino else None
        champ = self.books.get(getattr(self, "champion", ""), None)
        if not ep or not champ or not ctx.get("fut"):
            return None
        sig = (self.domino.state or {}).get("sigma15") or 1.0
        used = abs(ctx["fut"] - ep["fut0"]) / max(champ.p["L_star"] * sig, 1e-6)
        ivr = ctx.get("iv_rise_since_onset")
        if ivr is not None:
            used = max(used, ivr / config.IV_RISE_CAP)
        return round(float(min(max(used, 0.0), 2.0)), 3)

    def iv_change(self, secs):
        if not self.iv_hist or not self.atm_iv:
            return None
        target = self.now_s - secs
        old = [v for t, v in self.iv_hist if t <= target and v]
        if not old:
            return None
        return (self.atm_iv - old[-1]) * 100

    # ── books ──────────────────────────────────────────────────────────────
    def run_books(self, ctx):
        changed = False
        for name, b in self.books.items():
            t = paper.check_exit(b, ctx)
            if t:
                changed = True
                if name == self.champion:
                    audio.play("win" if t["pnl_pts"] > 0 else "loss")
                if name in (self.champion, "RAW"):
                    tag = "EXIT" if name == self.champion else "RAW-EXIT"
                    self.ev(tag, f"{t['rr']} {t['strike']:.0f} {t['lots']} lots · {t['entry']:.2f} → {t['exit']:.2f} "
                                 f"= {t['pnl_pts']:+.2f} pts / ₹{t['pnl_rs']:+,.0f} · {t['reason']} · capital ₹{b.capital:,.0f}")
            gates = [] if name == "RAW" else self.gates
            fire, why = paper.evaluate_entry(b, ctx, gates)
            if name == self.champion:
                self.last_reason = why
            if fire:
                d = paper.entry_dir(b, ctx)
                opt, msg = paper.choose_contract(ctx, d, b)
                if not opt:
                    if name == self.champion:
                        self.last_reason = msg
                    continue
                pos = paper.open_trade(b, ctx, opt, why)
                if pos:
                    changed = True
                    if name == self.champion:
                        audio.play("entry")
                    if name in (self.champion, "RAW"):
                        tag = "ENTRY" if name == self.champion else "RAW-ENTRY"
                        self.ev(tag, f"BUY {pos['lots']} lots NIFTY {pos['strike']:.0f} {pos['rr']} "
                                     f"({pos['expiry']}) @ {pos['entry']:.2f} · {why}")
        if changed:
            paper.save_books(self.books, self.day)

    # ── publish ────────────────────────────────────────────────────────────
    def publish(self):
        snap = self.m.snap
        if snap is None or not self.items:
            return
        ctx = self.ctx or {}
        heroes = []
        oi5 = self.oi_hist[0][1] if self.oi_hist else {}
        for i, rr, k in self.heroes():
            g = self.greek.get(i, {})
            heroes.append({
                "id": i, "rr": rr, "strike": k,
                "iv": g.get("iv"), "delta": g.get("delta"), "theta": g.get("theta_min"), "vega": g.get("vega"),
                "sb": fnum(self.m.sb[i, self.m.k], 0), "ss": fnum(self.m.ss[i, self.m.k], 0),
                "sbo": fnum(self.m.sbo[i, self.m.k], 0), "sso": fnum(self.m.sso[i, self.m.k], 0),
                "cls_b": CLS[int(self.flow.cls_b[i])], "cls_s": CLS[int(self.flow.cls_s[i])],
                "cls_bo": CLS[int(self.flow.cls_bo[i])], "cls_so": CLS[int(self.flow.cls_so[i])],
                "imb_q": fnum(self.flow.imb_q[i], 2), "imb_o": fnum(self.flow.imb_o[i], 2),
                "imb_t": fnum(self.flow.imb_t[i], 2), "lead": fnum(self.flow.lead[i], 2),
                "avg_b": fnum(self.flow.avg_b[i], 0), "avg_s": fnum(self.flow.avg_s[i], 0),
                "agg_b": fnum(self.flow.agg_b[i], 0), "agg_s": fnum(self.flow.agg_s[i], 0),
                "vol_s": fnum(self.flow.vol_s[i], 0),
                "oi_chg": fnum(float(snap["oi"][i]) - oi5.get(i, np.nan), 0),
                "run_up": fnum(self.flow.run_score(i, 1 if rr == "CE" else -1, self.m), 2),
            })
        dom = self.domino.state if self.domino else {}
        tiles = []
        for tile in dom.get("tiles", []):
            tiles.append(tile)
        eq = []
        for it in self.items:
            if it["kind"] != "eq":
                continue
            i = it["id"]
            ltp, prev = float(snap["ltp"][i]), float(snap["close"][i])
            fid = self.key.get(f"{it['sym']}|FUT")
            eq.append({"sym": it["sym"], "group": it.get("group"), "wn": it.get("wn"), "wb": it.get("wb"), "wf": it.get("wf"),
                       "id": i, "fid": fid,
                       "chg": fnum((ltp / prev - 1) * 100, 2) if prev > 0 and ltp > 0 else None,
                       "cls_b": CLS[int(self.flow.cls_b[i])], "cls_s": CLS[int(self.flow.cls_s[i])],
                       "agg": fnum(self.flow.agg_b[i] - self.flow.agg_s[i], 0),
                       "fut_oi_chg": fnum(float(snap["oi"][fid]) - oi5.get(fid, np.nan), 0) if fid is not None else None})
        champ = self.books.get(self.champion)
        pos = None
        if champ and champ.pos:
            p = champ.pos
            o = (ctx.get("by_key", {}).get(p["key"]) if ctx else None)
            if o and o["id"] != p["id"]:
                p["id"] = o["id"]                   # follow the contract if its row moved
            last = (o or {}).get("ltp") or p.get("last") or p["entry"]
            pos = dict(p, last=last, pnl_pts=round(last - p["entry"], 2),
                       pnl_rs=round((last - p["entry"]) * p["qty"], 0),
                       g=self.greek.get(p["id"], {}))
            pos.pop("advisors", None)
        state = {
            "mode": self.mode, "now": self.now_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "feed": FEED_STATES.get(int(self.t.c("feed_state")), "?"),
            "hot_p50": fnum(self.t.c("hot_p50_us"), 1), "hot_p99": fnum(self.t.c("hot_p99_us"), 1),
            "msgs_s": fnum(self.t.c("msgs_per_s"), 0), "rest_today": int(self.t.c("rest_today")),
            "reconnects": int(self.t.c("reconnects")), "loop_ms": fnum(self.loop_ms, 1),
            "vix": fnum(self.t.c("vix"), 2), "atm": getattr(self, "atm", None), "fwd": fnum(getattr(self, "fwd", None), 1),
            "atm_iv": fnum(self.atm_iv * 100 if getattr(self, "atm_iv", None) else None, 2),
            "iv5": fnum(self.iv_change(300), 2), "w0": self.w0, "w1": self.w1,
            "heroes": heroes, "K_up": fnum(ctx.get("K_up"), 2), "K_dn": fnum(ctx.get("K_dn"), 2),
            "domino": {k: v for k, v in dom.items() if k != "tiles"}, "tiles": tiles, "eq": eq,
            "episode": self.domino.episode_view(self.now_s) if self.domino else None,
            "iv_rise": fnum(ctx.get("iv_rise_since_onset"), 2),
            "reason": self.last_reason, "advisors": self.advisors,
            "pressure": self.pressure.view(ctx.get("spot") or ctx.get("fut")),
            "chain": self.pressure.chain_view(ctx.get("spot") or ctx.get("fut")),
            "fut": fnum(ctx.get("fut"), 2), "spot": fnum(ctx.get("spot"), 2),
            "fut_prev": fnum(snap["close"][self.fut_id], 2) if self.fut_id is not None and snap["close"][self.fut_id] > 0 else None,
            "late": self.lateness(ctx),
            "straddle": self.straddle.view(), "bank": self.bank.view(), "lag": self.lag.view(),
            "straddle_watch": self.watch.view(series=True),
            "gex": self.gex.v,
            "event": event_today(self.day),
            "fut_book": self.fut_book(),
            "episodes_logged": self.eplog.count if self.eplog else 0,
            "force": self.force.view(),
            "params": self.books[self.champion].p if champ else None,
            "champion": self.champion, "gates": self.gates,
            "learning": {k: self.lstate.get(k) for k in ("status", "scoreboard", "champion_since", "retired")},
            "book": champ.stats() if champ else None, "pos": pos,
            "trades": [{k: t.get(k) for k in ("time_in", "time_out", "rr", "strike", "lots", "entry", "exit",
                                              "pnl_pts", "pnl_rs", "reason", "capital_after", "ep_type")}
                       for t in (champ.trades[-25:] if champ else [])][::-1],
            "variants": sorted([b.stats() for b in self.books.values()], key=lambda s: -s["pnl_pts"]),
            "events": list(self.events)[:60],
        }
        self.blob.write(clean(state))

    def run(self):
        log(f"starting in {self.mode} mode")
        src = audio.init(log)
        log(f"audio: {src}" if src else "audio: off")
        while not int(self.t.c("stop")):
            self.load_registry()
            if self.items:
                break
            time.sleep(0.2)
        while not int(self.t.c("stop")):
            t0 = time.perf_counter()
            try:
                self.load_registry()
                self.step()
                if time.monotonic() - self.last_publish >= 0.25:
                    self.last_publish = time.monotonic()
                    self.publish()
            except Exception:
                log(traceback.format_exc())
                time.sleep(0.5)
            self.loop_ms = (time.perf_counter() - t0) * 1000
            self.t.set("engine_hb_ns", time.time_ns())
            if int(self.t.c("feed_state")) == 7 and self.mode != "live":   # replay finished
                break
            speed = max(float(self.t.c("speed")), 1.0)
            time.sleep(max(0.1 / speed - (time.perf_counter() - t0), 0.005))
        if self.books:
            paper.save_books(self.books, self.day)
            if self.eplog:
                self.eplog.close()
            self.watch.close()
            if self.mode != "live" or config.hm(self.now_dt) >= config.mins((15, 30)):
                self.end_day()
        self.publish()
        log("stopped")


def main():
    global LOG
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Ctrl+C is the supervisor's: it sets ctrl.stop
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)   # NaN = "no quote yet"
    mode = sys.argv[1] if len(sys.argv) > 1 else "live"
    LOG = open(os.path.join(config.LOG_DIR, "engine.log"), "a", encoding="utf-8")
    t = Table()
    blob = StateBlob()
    Engine(t, blob, mode).run()


if __name__ == "__main__":
    main()
