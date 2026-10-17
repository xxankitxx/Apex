"""
Straddle watch — the owner's observation (17 Oct 2026, evening):

  "A straddle falls from 9:15 to the close. When the straddle value SPIKES, one
   leg has picked up gamma — its delta keeps rising and it stops decaying and
   moves sharply. After that the ATM rolls, and straddle charts jump to another
   level. Those are the moments to buy the leg whose gamma and delta are rising."

The existing `Straddle` (extras.py) follows the LIVE ATM, restarting at every roll —
that is exactly the chart that "shifts to some other level".  This watch keeps a
FIXED strike instead, so a spike is measured on one contract pair from start to end:

  anchor K    the ATM when the watch starts (re-anchored only after spot has
              settled ≥ 2 strikes away, or 1 strike away for 10 minutes)
  S(t)        CE_K + PE_K — mid when both sides are quoted, else LTP — at 1 Hz
  expected    theta_min(CE_K) + theta_min(PE_K): what S SHOULD lose per minute
  excess      ΔS over 5 min minus the theta-expected change: the spike measure
  threshold   max(SPIKE_MIN_PTS, SPIKE_MIN_FRAC × S, SPIKE_SIGMA × running |excess|)
  legs        each leg's 5-min change, delta now vs 5 min ago, gamma, 1-min
              acceleration — the leg that carries the spike is the GAMMA LEG
  state       WARMING · DECAYING · FLAT · VOL-SPIKE (both legs up: IV, not
              direction) · SPIKE CE · SPIKE PE
  shifts      every ATM roll: time, old → new strike, S before / after
  spikes      every spike event, with what followed (+1 / +5 / +10 min) — written
              to data/paper/straddle_DAY.jsonl for the learning loop

Used by: advisor "gamma_leg" (vetoes an entry against a live directional spike) and
the pre-registered paper variant "straddle_spike" (buys the gamma leg itself).
Everything here is derived from the shared table; nothing is sent anywhere.
"""
import json
import math
import os
from collections import deque

from .. import config


def _f(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


class StraddleWatch:
    WINDOW_S = 300.0            # the spike window (5 min)
    SERIES_DT = 10.0            # panel series resolution (s)
    SERIES_KEEP_S = 2 * 3600    # panel series depth
    EVIDENCE_OFFSETS = (60, 300, 600)

    def __init__(self, day=""):
        self.day = day
        self.K = None
        self.since = None           # (t_s, hh:mm:ss) of the anchor
        self.open_px = None         # S at the anchor
        self.hist = deque(maxlen=1200)      # (t, S, ce, pe, dce, dpe) at 1 Hz, 20 min
        self.series = deque()               # [t, S, ce, pe, expected] every SERIES_DT
        self.expected = None        # theta-integrated path of S since the anchor
        self.vwap = None
        self._pv = self._v = 0.0
        self.sigma = config.SPIKE_SIGMA_SEED
        self._n = 0
        self.state = "WARMING"
        self.leg = None
        self.spike = None           # the live spike event (dict) or None
        self.spikes = []            # today's finished + live spike summaries (last 12 kept)
        self.shifts = []            # ATM rolls
        self.events = []            # ("SPIKE"/"SHIFT", text) raised since the last drain
        self._pending = []          # evidence records still collecting +1/+5/+10 min
        self._away_since = None     # when the live ATM first differed from K
        self._roll_to = None        # new strike to re-anchor on (the engine supplies its quote)
        self._below_since = None    # when excess first fell below the end line
        self._last_end = None       # when the last spike ended (cooldown)
        self._last_1hz = 0.0
        self._last_series = 0.0
        self.px = self.ce = self.pe = None
        self.theta_min = None
        self.drift_min = None
        self.chg5 = self.excess = self.thr = None
        self.legs = {}
        self.fut = None
        self.path = os.path.join(config.PAPER_DIR, f"straddle_{day}.jsonl") if day else None

    # ── anchoring ──────────────────────────────────────────────────────────
    def _anchor(self, K, now_s, now_dt, px, reason):
        if self.K is not None and px is not None:
            self.shifts.append({"t": now_dt.strftime("%H:%M:%S"), "t_s": round(now_s, 1), "from": self.K, "to": K,
                                "s_before": _f(self.px), "s_after": _f(px), "why": reason})
            self.events.append(("SHIFT", f"ATM rolled {self.K:.0f} → {K:.0f}: straddle {self.px:.1f} → {px:.1f} ({reason})"))
            if self.spike:
                self._end_spike(now_s, now_dt, "atm rolled")
        self.K = K
        self.since = (now_s, now_dt.strftime("%H:%M:%S"))
        self.open_px = px
        self.expected = px
        self.hist.clear()
        self._pv = self._v = 0.0
        self.vwap = None
        self._away_since = None
        self.state = "WARMING"
        self.leg = None
        self.drift_min = self.chg5 = self.excess = None     # measured on the new strike only
        self.legs = {}

    # ── one step (called every engine step; cheap) ─────────────────────────
    def update(self, now_s, now_dt, atm, quote, greek, fut, vol_delta=0.0):
        """quote: {"CE": (ltp, bid, ask), "PE": (...)} for strike K (or the candidate K);
        greek: {"CE": {delta, gamma, theta_min}, "PE": {...}}; vol_delta: traded qty since the last step."""
        self.fut = fut
        if atm is None:
            return
        if self.K is None:
            px = self._price(quote)
            if px is None:
                return
            self._anchor(atm, now_s, now_dt, px, "session open")
        px = self._price(quote)
        if px is None:
            return
        ce, pe = self._mid(quote.get("CE")), self._mid(quote.get("PE"))
        self.px, self.ce, self.pe = px, ce, pe
        gce, gpe = (greek or {}).get("CE") or {}, (greek or {}).get("PE") or {}
        th = None
        if gce.get("theta_min") is not None and gpe.get("theta_min") is not None:
            th = float(gce["theta_min"]) + float(gpe["theta_min"])
        self.theta_min = th
        if vol_delta and vol_delta > 0:
            self._pv += px * vol_delta
            self._v += vol_delta
            self.vwap = self._pv / self._v
        # 1 Hz history
        if now_s - self._last_1hz >= 1.0:
            dt = now_s - self._last_1hz if self._last_1hz else 1.0
            self._last_1hz = now_s
            if self.expected is not None and th is not None:
                self.expected += th * min(dt, 5.0) / 60.0
            self.hist.append((now_s, px, ce, pe, gce.get("delta"), gpe.get("delta")))
            self._measure(now_s, now_dt, gce, gpe)
        if now_s - self._last_series >= self.SERIES_DT:
            self._last_series = now_s
            self.series.append([round(now_s, 1), _f(px, 2), _f(ce, 2), _f(pe, 2), _f(self.expected, 2)])
            while self.series and now_s - self.series[0][0] > self.SERIES_KEEP_S:
                self.series.popleft()
        # ATM roll: re-anchor only once spot has settled away from K
        if atm != self.K:
            if self._away_since is None:
                self._away_since = now_s
            away = now_s - self._away_since
            far = abs(atm - self.K) >= 2 * config.STRIKE_STEP
            if (far and away >= 120) or away >= 600:
                self._roll_to = atm           # the engine supplies the new strike's quote next step
        else:
            self._away_since = None
        self._advance_evidence(now_s, now_dt)

    def wants_roll(self):
        return self._roll_to

    def roll(self, now_s, now_dt, atm, quote):
        """Called by the engine with the NEW strike's quote once wants_roll() is set."""
        self._roll_to = None
        px = self._price(quote)
        if px is None:
            return
        self._anchor(atm, now_s, now_dt, px, "spot settled at the new strike")

    # ── the measure ────────────────────────────────────────────────────────
    def _measure(self, now_s, now_dt, gce, gpe):
        h = self.hist
        if len(h) < 3:
            return
        old = [r for r in h if r[0] <= now_s - self.WINDOW_S]
        o10 = [r for r in h if r[0] <= now_s - 600]
        o1 = [r for r in h if r[0] <= now_s - 60]
        o2 = [r for r in h if r[0] <= now_s - 120]
        if o10:
            self.drift_min = (self.px - o10[-1][1]) / 10.0
        if not old:
            self.state = "WARMING"
            return
        ref = old[-1]
        chg5 = self.px - ref[1]
        expected5 = (self.theta_min or 0.0) * (self.WINDOW_S / 60.0)
        excess = chg5 - expected5
        self.chg5, self.excess = chg5, excess
        # running scale of |excess| (same EWMA idea as sigma15), seeded, 20-min half-life —
        # learned from quiet time only, so a spike does not raise the bar for the next one
        thr = max(config.SPIKE_MIN_PTS, config.SPIKE_MIN_FRAC * ref[1], config.SPIKE_SIGMA * max(self.sigma, 0.5))
        if self.spike is None and abs(excess) < thr:
            self._n += 1
            a = max(1.0 / (self._n + 1), 1 - math.exp(-math.log(2) / config.SIGMA_HALF_LIFE_S))
            self.sigma += a * (abs(excess) - self.sigma)
            thr = max(config.SPIKE_MIN_PTS, config.SPIKE_MIN_FRAC * ref[1], config.SPIKE_SIGMA * max(self.sigma, 0.5))
        self.thr = thr
        # legs
        legs = {}
        for name, i_px, i_d, g in (("CE", 2, 4, gce), ("PE", 3, 5, gpe)):
            now_px = h[-1][i_px]
            chg = (now_px - ref[i_px]) if (now_px is not None and ref[i_px] is not None) else None
            c1 = (now_px - o1[-1][i_px]) if (o1 and now_px is not None and o1[-1][i_px] is not None) else None
            c0 = (o1[-1][i_px] - o2[-1][i_px]) if (o1 and o2 and o1[-1][i_px] is not None and o2[-1][i_px] is not None) else None
            d_now, d_old = g.get("delta"), ref[i_d]
            legs[name] = {"px": _f(now_px), "chg5": _f(chg), "chg1": _f(c1), "acc": _f(c1 - c0) if (c1 is not None and c0 is not None) else None,
                          "delta": _f(d_now, 3), "delta5": _f(d_old, 3),
                          "ddelta": _f(abs(float(d_now)) - abs(float(d_old)), 3) if (d_now is not None and d_old is not None) else None,
                          "gamma": _f(g.get("gamma"), 5), "theta": _f(g.get("theta_min"), 4)}
        self.legs = legs
        up = {k: (v["chg5"] or 0.0) for k, v in legs.items()}
        winner = max(up, key=up.get)
        loser = "PE" if winner == "CE" else "CE"
        directional = excess >= thr and up[winner] >= 0.6 * max(chg5, 1e-9) and up[loser] <= 0.35 * up[winner]
        vol_spike = excess >= thr and not directional and up[loser] > 0
        if self.spike is None:
            cooling = self._last_end is not None and now_s - self._last_end < config.SPIKE_COOLDOWN_S
            if directional and not cooling:
                self._start_spike(now_s, now_dt, winner, excess, legs[winner])
            elif vol_spike:
                self.state, self.leg = "VOL-SPIKE", None
            else:
                self.leg = None
                self.state = "DECAYING" if chg5 < 0 else "FLAT"
        else:
            sp = self.spike
            sp["age"] = round(now_s - sp["t0_s"], 1)
            sp["peak_excess"] = max(sp["peak_excess"], excess)
            lp = legs[sp["leg"]]["px"]
            if lp is not None:
                sp["leg_peak"] = max(sp.get("leg_peak") or lp, lp)
                sp["leg_move"] = _f(lp - sp["leg_px0"])
            if self.fut is not None and sp.get("fut0") is not None:
                sp["fut_move"] = _f((self.fut - sp["fut0"]) * (1 if sp["leg"] == "CE" else -1), 1)
            if legs[sp["leg"]]["delta"] is not None:
                sp["delta_now"] = legs[sp["leg"]]["delta"]
            self.state, self.leg = f"SPIKE {sp['leg']}", sp["leg"]
            gain = (sp.get("leg_peak") or 0.0) - (sp.get("leg_px0") or 0.0)
            gave_back = lp is not None and gain >= 2.0 and lp <= sp["leg_peak"] - 0.5 * gain
            if sp["age"] >= 1200:
                self._end_spike(now_s, now_dt, "20 min: a trend now, not a spike")
            elif lp is not None and (sp.get("leg_move") or 0.0) <= 0.0 and sp["age"] >= 60:
                self._end_spike(now_s, now_dt, f"{sp['leg']} leg back below its start")
            elif gave_back:
                self._end_spike(now_s, now_dt, f"{sp['leg']} leg gave back half its move")
            elif excess < 0.4 * thr:
                if self._below_since is None:
                    self._below_since = now_s
                elif now_s - self._below_since >= 60:
                    self._end_spike(now_s, now_dt, "premium stopped expanding")
            else:
                self._below_since = None

    def _start_spike(self, now_s, now_dt, leg, excess, legv):
        sp = {"id": int(now_s), "t0": now_dt.strftime("%H:%M:%S"), "t0_s": now_s, "t_s": round(now_s, 1), "leg": leg, "K": self.K,
              "s0": _f(self.px), "excess0": _f(excess), "thr": _f(self.thr), "peak_excess": excess,
              "fut0": self.fut, "leg_px0": legv["px"], "leg_peak": legv["px"], "leg_move": 0.0,
              "delta0": legv["delta"], "delta_now": legv["delta"], "gamma0": legv["gamma"], "age": 0.0, "fut_move": 0.0}
        self.spike = sp
        self._below_since = None
        self.state, self.leg = f"SPIKE {leg}", leg
        self.spikes.append(sp)
        self.spikes = self.spikes[-12:]
        self.events.append(("SPIKE", f"straddle {self.K:.0f} +{excess:.1f} over theta in 5 min — {leg} leg carries it "
                                     f"({legv['px']:.1f}, delta {legv['delta5']}→{legv['delta']}, gamma {legv['gamma']})"))
        self._pending.append({"t0_s": now_s, "done": set(), "rec": {
            "day": self.day, "t0": sp["t0"], "leg": leg, "K": self.K, "s0": sp["s0"], "excess0": sp["excess0"],
            "thr": sp["thr"], "fut0": self.fut, "leg_px0": legv["px"], "delta0": legv["delta"], "gamma0": legv["gamma"],
            "after": {}}})

    def _end_spike(self, now_s, now_dt, why):
        sp = self.spike
        if sp:
            sp["ended"] = now_dt.strftime("%H:%M:%S")
            sp["end_s"] = round(now_s, 1)
            sp["end_why"] = why
            sp.pop("t0_s", None)
        self.spike = None
        self._below_since = None
        self._last_end = now_s
        self.state, self.leg = "DECAYING", None

    def _advance_evidence(self, now_s, now_dt):
        for st in list(self._pending):
            age = now_s - st["t0_s"]
            for off in self.EVIDENCE_OFFSETS:
                if off not in st["done"] and age >= off:
                    st["done"].add(off)
                    leg = st["rec"]["leg"]
                    lp = (self.legs.get(leg) or {}).get("px")
                    st["rec"]["after"][str(off)] = {"fut": _f(self.fut, 1), "s": _f(self.px), "leg_px": lp,
                                                   "delta": (self.legs.get(leg) or {}).get("delta"), "K_now": self.K}
            if len(st["done"]) == len(self.EVIDENCE_OFFSETS):
                self._flush(st["rec"]); self._pending.remove(st)

    def _flush(self, rec):
        if not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception:
            pass

    def close(self):
        for st in list(self._pending):
            self._flush(st["rec"])
        self._pending.clear()

    # ── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _mid(q):
        if not q:
            return None
        ltp, bid, ask = q
        try:
            if bid and ask and bid > 0 and ask >= bid and (ask - bid) <= max(0.08 * ask, 1.0):
                return (float(bid) + float(ask)) / 2.0
            return float(ltp) if ltp and ltp > 0 else None
        except (TypeError, ValueError):
            return None

    def _price(self, quote):
        ce, pe = self._mid((quote or {}).get("CE")), self._mid((quote or {}).get("PE"))
        if ce is None or pe is None:
            return None
        return ce + pe

    def drain_events(self):
        ev, self.events = self.events, []
        return ev

    # ── views ──────────────────────────────────────────────────────────────
    def advise(self, d):
        """Would-have verdict for an entry in direction d (+1 CE / −1 PE)."""
        sp = self.spike
        if sp and sp.get("age", 0) <= 600:
            want = "CE" if d > 0 else "PE"
            if sp["leg"] != want:
                return True, f"straddle {self.K:.0f} spike is on the {sp['leg']} leg (+{sp['leg_move']}), not the {want}"
            return False, f"straddle spike on the {sp['leg']} leg agrees (+{sp['leg_move']}, delta {sp['delta0']}→{sp['delta_now']})"
        if self.state == "VOL-SPIKE":
            return False, "straddle up on both legs (IV), no leg favoured"
        if self.drift_min is not None and self.theta_min is not None:
            return False, f"straddle {self.state.lower()}: {self.drift_min:+.2f}/min vs theta {self.theta_min:+.2f}"
        return False, "straddle warming"

    def view(self, series=True):
        v = {"K": self.K, "since": self.since[1] if self.since else None, "px": _f(self.px), "ce": _f(self.ce), "pe": _f(self.pe),
             "open_px": _f(self.open_px), "vwap": _f(self.vwap), "expected": _f(self.expected),
             "theta_min": _f(self.theta_min, 3), "drift_min": _f(self.drift_min, 3),
             "chg5": _f(self.chg5), "excess": _f(self.excess), "thr": _f(self.thr), "sigma": _f(self.sigma),
             "state": self.state, "leg": self.leg, "legs": self.legs,
             "spike": {k: v for k, v in self.spike.items() if k != "t0_s"} if self.spike else None,
             "spikes": [{k: v for k, v in s.items() if k != "t0_s"} for s in self.spikes][::-1],
             "shifts": self.shifts[-12:]}
        if series:
            v["series"] = list(self.series)
        return v
