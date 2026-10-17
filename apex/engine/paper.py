"""
Paper trading — the owner's rule exactly, on paper.

  capital = ₹1,00,000 at the start of each trading day
  lots    = floor(capital / (premium x 65))        all-in, every trade
  after each exit: capital += P&L (gross; slippage and charges ignored — owner,
  17 Oct 2026). Bid/ask at entry and exit are recorded alongside for reference.

v1 trigger (D-033), evaluated every 100 ms by each variant's book:
  1. impulse   : Nifty-futures 15-s z >= m*  (in direction d)
  2. structure : weighted basket synchrony S_d >= s*
  3. not late  : |futures move since episode onset| <= L* x sigma15, and
                 ATM IV up <= 1.5 vol points since onset
  plus: flat, inside 09:25-15:15 (0DTE: no entries after 14:45), once per episode.
Exits (the only four):
  * stop      : futures moves d* against the entry
  * trail     : once futures is +d* (1R) in favour, stop = best - d*
  * thesis    : synchrony flips — opposite-direction S >= s* with z >= 1 against
  * time      : flat at 15:25; 0DTE flat at 15:00 unless |delta| >= 0.9
Advisors' would-have verdicts are stored with every trade for the learning loop.
"""
import json
import os

import numpy as np

from .. import config


class Book:
    def __init__(self, name, params, day):
        self.name = name
        self.p = dict(params)
        self.day = day
        self.capital = config.START_CAPITAL
        self.pos = None
        self.trades = []
        self.fired_episodes = set()
        self.blocked = ""

    # ── persistence ────────────────────────────────────────────────────────
    def to_json(self):
        return {"name": self.name, "p": self.p, "day": self.day, "capital": self.capital,
                "pos": self.pos, "trades": self.trades, "fired": sorted(self.fired_episodes)}

    @classmethod
    def from_json(cls, d):
        b = cls(d["name"], d["p"], d["day"])
        b.capital = d["capital"]; b.pos = d["pos"]; b.trades = d["trades"]
        b.fired_episodes = set(d.get("fired", []))
        return b

    # ── stats ──────────────────────────────────────────────────────────────
    def stats(self):
        pts = [t["pnl_pts"] for t in self.trades]
        wins = [x for x in pts if x > 0]
        return {"name": self.name, "trades": len(pts), "wins": len(wins),
                "pnl_pts": round(sum(pts), 2),
                "pnl_rs": round(sum(t["pnl_rs"] for t in self.trades), 0),
                "capital": round(self.capital, 0),
                "win_rate": round(100.0 * len(wins) / len(pts), 1) if pts else None,
                "open": bool(self.pos)}


def entry_dir(book, ctx):
    """Direction a book would trade now: the spike leg for the straddle_spike book, else the domino's."""
    if book.p.get("spike"):
        sp = (ctx.get("straddle_watch") or {}).get("spike")
        if sp:
            return 1 if sp["leg"] == "CE" else -1
    return ctx["domino"]["dir"]


def spike_leg(ctx):
    """The anchored straddle's spiking leg as an option row, or (None, reason)."""
    sw = ctx.get("straddle_watch") or {}
    sp = sw.get("spike")
    if not sp or sw.get("K") is None:
        return None, "no straddle spike"
    o = ctx["by_key"].get(f"NIFTY|OPT|{ctx['w0']}|{int(sw['K'])}|{sp['leg']}")
    if not o or not o["ltp"]:
        return None, f"no quote for {int(sw['K'])} {sp['leg']}"
    if not (config.MIN_PREMIUM <= o["ltp"] <= config.MAX_PREMIUM):
        return None, f"{int(sw['K'])} {sp['leg']} premium {o['ltp']:.1f} outside {config.MIN_PREMIUM:.0f}-{config.MAX_PREMIUM:.0f}"
    if o["age"] >= 15:
        return None, f"{int(sw['K'])} {sp['leg']} quote is {o['age']:.0f} s old"
    return o, ""


def choose_contract(ctx, d, book=None):
    """v1 rule (D-036): DTE delta band -> nearest-the-money strike inside the band.
    The straddle_spike book buys the spiking leg itself instead.
    Returns the option dict or (None, reason)."""
    if book is not None and book.p.get("spike"):
        return spike_leg(ctx)
    now = ctx["now_dt"]
    opts = ctx["options"]                 # list of dicts with id, strike, rr, week, expiry, ltp, delta, age
    rr = "CE" if d > 0 else "PE"
    w0_exp = ctx["w0"]
    zero_dte = now.date().isoformat() == w0_exp
    hmn = config.hm(now)
    week, band = 0, None
    if zero_dte:
        if hmn >= config.mins(config.ZERO_DTE_NO_ENTRY):
            week, band = 1, config.DELTA_BANDS["nextweek"]
        elif hmn >= config.mins(config.ZERO_DTE_NEXTWEEK_FROM):
            week, band = 1, config.DELTA_BANDS["nextweek"]
        else:
            band = config.DELTA_BANDS["zero_am"]
    else:
        dte = (np.datetime64(w0_exp) - np.datetime64(now.date().isoformat())).astype(int)
        band = config.DELTA_BANDS["ge3"] if dte >= 3 else config.DELTA_BANDS["1to2"]
    lo, hi = band
    cands = [o for o in opts if o["rr"] == rr and o["week"] == week and o.get("delta") is not None
             and o["ltp"] and config.MIN_PREMIUM <= o["ltp"] <= config.MAX_PREMIUM and o["age"] < 15]
    inband = [o for o in cands if lo <= abs(o["delta"]) <= hi]
    if inband:
        return min(inband, key=lambda o: abs(o["delta"])), ""
    above = [o for o in cands if abs(o["delta"]) >= lo]
    if above:
        return min(above, key=lambda o: abs(o["delta"])), ""
    return None, f"no {rr} in delta band {lo:.2f}-{hi:.2f}"


def evaluate_entry(book, ctx, gates):
    """Returns (fire: bool, reason: str). One composite condition, one reason."""
    p = book.p
    dom = ctx["domino"]
    ep = ctx["episode"]
    now = ctx["now_dt"]
    hmn = config.hm(now)
    if book.pos is not None:
        return False, "in position"
    if hmn < config.mins(config.SUPPRESS_UNTIL) or hmn >= config.mins(config.LAST_ENTRY):
        return False, "outside entry window"
    if p.get("spike"):                       # straddle_spike book: the owner's gamma-leg idea
        return evaluate_spike_entry(book, ctx, gates)
    if ep is None:
        return False, "no episode"
    if ep["id"] in book.fired_episodes:
        return False, "already traded this episode"
    d = dom["dir"]
    if d != ep["dir"]:
        return False, "impulse against the episode"
    z = dom["z"] * d
    S = dom["S_up"] if d > 0 else dom["S_dn"]
    gap = dom.get("gap", 0.0) * d
    if p.get("gap_star"):                    # basket-gap variant: the basket leads, futures lag
        if gap < p["gap_star"]:
            return False, f"basket gap {gap:.1f} < {p['gap_star']}"
        if z < p["m_star"]:
            return False, f"impulse z {z:.1f} < {p['m_star']}"
    elif z < p["m_star"]:
        return False, f"impulse z {z:.1f} < {p['m_star']}"
    if S < p["s_star"]:
        return False, f"synchrony {S:.2f} < {p['s_star']}"
    moved = abs(ctx["fut"] - ep["fut0"])
    if moved > p["L_star"] * dom["sigma15"]:
        return False, f"LATE: futures already {moved:.0f} pts since onset"
    iv_rise = ctx.get("iv_rise_since_onset")
    if iv_rise is not None and iv_rise > config.IV_RISE_CAP:
        return False, f"LATE: ATM IV +{iv_rise:.1f} since onset"
    for g in gates:                         # advisors promoted by the learning loop
        if ctx["advisors"].get(g, {}).get("veto"):
            return False, f"gate {g}: {ctx['advisors'][g]['why']}"
    return True, (f"{ep['type'].lower()} move {'UP' if d > 0 else 'DOWN'}: futures z {z:.1f}, "
                  f"synchrony {S:.0%}, first mover {ep['first'] or '—'}, "
                  f"{moved:.0f} pts since onset")


def evaluate_spike_entry(book, ctx, gates):
    """straddle_spike book: a directional spike on the anchored straddle, caught early,
    with the carrying leg's delta rising. One trade per spike (spike ids are stored
    negated in fired_episodes so they never collide with episode ids)."""
    sw = ctx.get("straddle_watch") or {}
    sp = sw.get("spike")
    if not sp:
        return False, f"straddle {sw.get('state', 'warming').lower()}"
    if -int(sp["id"]) in book.fired_episodes:
        return False, "already traded this spike"
    if sp.get("age", 0.0) > config.SPIKE_ENTRY_MAX_AGE_S:
        return False, f"LATE: spike is {sp['age']:.0f} s old"
    leg = (sw.get("legs") or {}).get(sp["leg"]) or {}
    dd = leg.get("ddelta")
    if dd is None or dd < config.SPIKE_MIN_DDELTA:
        return False, f"{sp['leg']} delta not rising ({dd})"
    for g in gates:
        if ctx["advisors"].get(g, {}).get("veto"):
            return False, f"gate {g}: {ctx['advisors'][g]['why']}"
    return True, (f"straddle {sw['K']:.0f} spiked +{sp['peak_excess']:.1f} over theta; {sp['leg']} leg carries it "
                  f"(delta {leg.get('delta5')}→{leg.get('delta')}, gamma {leg.get('gamma')}), {sp['age']:.0f} s in")


def open_trade(book, ctx, opt, reason):
    px = opt["ltp"]
    lots = int(book.capital // (px * config.LOT_SIZE))
    if lots < 1:
        book.blocked = f"premium ₹{px:.1f} unaffordable"
        return None
    d = 1 if opt["rr"] == "CE" else -1
    qty = lots * config.LOT_SIZE
    ep = ctx.get("episode") or {}
    sp = (ctx.get("straddle_watch") or {}).get("spike") if book.p.get("spike") else None
    ep_id = -int(sp["id"]) if sp else ep.get("id")
    book.pos = {
        "key": opt["key"], "id": opt["id"], "strike": opt["strike"], "rr": opt["rr"],
        "expiry": opt["expiry"], "lots": lots, "qty": qty, "slices": -(-qty // config.FREEZE_QTY),
        "entry": px, "entry_bid": opt.get("bid"), "entry_ask": opt.get("ask"),
        "t_in": ctx["now_s"], "time_in": ctx["now_dt"].strftime("%H:%M:%S"),
        "dir": d, "fut_in": ctx["fut"], "best": ctx["fut"], "trail": False,
        "delta_in": opt.get("delta"), "iv_in": opt.get("iv"),
        "why": reason, "advisors": ctx["advisors"], "episode": ep_id,
        "ep_type": "STRADDLE-SPIKE" if sp else ep.get("type"), "peak_pts": 0.0,
    }
    if ep_id is not None:
        book.fired_episodes.add(ep_id)
    return book.pos


def check_exit(book, ctx):
    pos = book.pos
    if pos is None:
        return None
    p = book.p
    d = pos["dir"]
    fut = ctx["fut"]
    o = ctx.get("by_key", {}).get(pos["key"]) or ctx["by_id"].get(pos["id"])
    if o and o["id"] != pos["id"]:
        pos["id"] = o["id"]                      # the contract's row moved (feed restart / re-centre)
    px = o["ltp"] if o and o["ltp"] else None
    if px:
        pos["last"] = px
        pos["peak_pts"] = max(pos["peak_pts"], px - pos["entry"])
    fav = (fut - pos["fut_in"]) * d
    pos["best"] = max(pos["best"], fut) if d > 0 else min(pos["best"], fut)
    best_fav = (pos["best"] - pos["fut_in"]) * d
    reason = None
    if best_fav >= p["d_star"]:
        pos["trail"] = True
    stop_level = (pos["best"] - d * p["d_star"]) if pos["trail"] else (pos["fut_in"] - d * p["d_star"])
    pos["stop_fut"] = stop_level
    if (fut - stop_level) * d <= 0:
        reason = "TRAIL" if pos["trail"] else "STOP"
    dom = ctx["domino"]
    S_opp = dom["S_dn"] if d > 0 else dom["S_up"]
    if reason is None and S_opp >= p["s_star"] and dom["z"] * d <= -1.0:
        reason = "THESIS-VOID (synchrony flipped)"
    if reason is None and p.get("exit_book") and o is not None:
        bk = ctx.get("book_state", {}).get(o["id"])
        # sellers refilling on the held contract (both qty and orders) while futures have stalled
        if bk and bk["opp_q"] == 1 and bk["opp_o"] == 1 and fav < 0.5 * p["d_star"] and ctx["now_s"] - pos["t_in"] > 20:
            reason = "BOOK (sellers refilled on the held contract)"
    now = ctx["now_dt"]
    hmn = config.hm(now)
    zero_dte = pos["expiry"] == now.date().isoformat()
    if reason is None and hmn >= config.mins(config.FLATTEN_AT):
        reason = "TIME (15:25 flatten)"
    if reason is None and zero_dte and hmn >= config.mins(config.ZERO_DTE_FLATTEN):
        if not (o and o.get("delta") is not None and abs(o["delta"]) >= 0.9):
            reason = "TIME (0DTE 15:00)"
    if reason and px is None:
        px = pos.get("last", pos["entry"])
    if reason:
        return close_trade(book, ctx, px, reason, o)
    return None


def close_trade(book, ctx, px, reason, o=None):
    pos = book.pos
    pnl_pts = round(px - pos["entry"], 2)
    pnl_rs = round(pnl_pts * pos["qty"], 2)
    book.capital = round(book.capital + pnl_rs, 2)
    t = dict(pos)
    t.update({"exit": px, "exit_bid": (o or {}).get("bid"), "exit_ask": (o or {}).get("ask"),
              "time_out": ctx["now_dt"].strftime("%H:%M:%S"), "hold_s": ctx["now_s"] - pos["t_in"],
              "reason": reason, "pnl_pts": pnl_pts, "pnl_rs": pnl_rs,
              "fut_out": ctx["fut"], "capital_after": book.capital})
    book.trades.append(t)
    book.pos = None
    return t


def save_books(books, day):
    path = os.path.join(config.PAPER_DIR, f"{day}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({n: b.to_json() for n, b in books.items()}, f, default=str)
    os.replace(tmp, path)


def load_books(day):
    path = os.path.join(config.PAPER_DIR, f"{day}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {n: Book.from_json(v) for n, v in d.items()}
    except Exception:
        return None


def write_trades_csv(book, day):
    import csv
    path = os.path.join(config.PAPER_DIR, f"trades_{day}.csv")
    cols = ["time_in", "time_out", "rr", "strike", "expiry", "lots", "qty", "entry", "exit",
            "pnl_pts", "pnl_rs", "capital_after", "reason", "ep_type", "why",
            "entry_bid", "entry_ask", "exit_bid", "exit_ask", "fut_in", "fut_out", "hold_s"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in book.trades:
            w.writerow(t)
    return path
