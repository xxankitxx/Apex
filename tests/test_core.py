"""Offline checks: python -m pytest tests  (or python tests/test_core.py)."""
import os
import sys
import tempfile

os.environ["APEX_DATA"] = tempfile.mkdtemp(prefix="apex_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime  # noqa: E402

import numpy as np  # noqa: E402

from apex import config, greeks  # noqa: E402
from apex.engine import learning, paper  # noqa: E402
from apex.feed_core import Registry, apply_packet  # noqa: E402
from apex.table import Table  # noqa: E402


def test_calendar():
    n = datetime(2026, 10, 17, 10, 0, tzinfo=config.IST)
    w = config.weekly_expiries(n, 2)
    assert w[0].isoformat() == "2026-10-19"          # Tue 20 Oct is Dussehra -> Mon 19
    assert w[1].isoformat() == "2026-10-27"
    assert config.ws_expiry(w[0]) == "19-Oct-2026"


def test_apply_packet_segments():
    t = Table(create=True, name="apex_test_tbl")
    try:
        reg = Registry()
        eq = reg.add("HDFCBANK|EQ", "eq", "HDFCBANK", "4.1!1333", seg="eq")
        fo = reg.add("NIFTY|FUT", "fut", "NIFTY", "4.1!1333", seg="fo")   # same number, other segment
        bt = reg.by_token
        q_eq = ["4.1!1333", 1700, 1712.5, 1720, 1690, 0.5, 1712.4, 100, 1712.6, 120, 5, 1705,
                900000, 5000, 6000, 0, "", 0, 0, 1760000000, 1700]
        q_fo = ["4.1!1333", 25000, 25210, 25300, 24990, 0.4, 25209, 75, 25211, 150, 75, 25100,
                14500000, 1000, 2000000, 4000, 5000, 0, "", 0, 0, 1760000000, 25100]
        assert apply_packet(t, bt, q_eq, 1) == eq
        assert apply_packet(t, bt, q_fo, 2) == fo
        assert t.rows["ltp"][eq] == 1712.5 and t.rows["ttq"][eq] == 900000
        assert t.rows["ltp"][fo] == 25210 and t.rows["oi"][fo] == 14500000 and t.rows["ttq"][fo] == 2000000
        old = list(q_fo); old[14] = 1999000; old[2] = 1
        assert apply_packet(t, bt, old, 3) == -1                     # older cumulative volume dropped
        d = ["4.2!1333", 1760000000, [[25209, 75, 1, "N", 25211, 150, 2, "N"]] * 5]
        assert apply_packet(t, bt, d, 4) == fo and t.rows["bq"][fo][0] == 75
    finally:
        t.close(); t.unlink()


def test_greeks_roundtrip():
    F, T = 25200.0, 5 / 365
    K = np.array([25000., 25200., 25400.])
    c = np.array([True, True, False])
    px = greeks.b76_price(F, K, T, 0.13, c)
    iv = greeks.implied_vol(px, F, K, T, c)
    assert np.allclose(iv, 0.13, atol=1e-4)
    g = greeks.greeks(F, K, T, iv, c)
    assert 0.45 < g["delta"][1] < 0.55 and g["theta_min"][1] < 0


def test_paper_sizing_and_exit():
    b = paper.Book("x", config.TRIGGER, "2026-10-19")
    now = datetime(2026, 10, 21, 10, 0, tzinfo=config.IST)
    ep = {"id": 1, "dir": 1, "type": "BASKET-LED"}
    ctx = {"now_s": 0, "now_dt": now, "fut": 25200.0, "advisors": {}, "episode": ep}
    opt = {"id": 5, "key": "k", "strike": 25150, "rr": "CE", "expiry": "2026-10-27", "ltp": 150.0}
    pos = paper.open_trade(b, ctx, opt, "test")
    assert pos["lots"] == int(100000 // (150 * 65)) == 10
    ctx2 = dict(ctx, fut=25200 - 12.5, now_s=30, by_id={5: dict(opt, ltp=142.0)},
                domino={"S_up": 0, "S_dn": 0, "z": 0})
    t = paper.check_exit(b, ctx2)
    assert t and t["reason"] == "STOP" and t["pnl_rs"] == -8 * 650 and b.capital == 100000 - 5200


def test_learning_sprt():
    days = {}
    for i in range(12):
        day = f"2026-11-{i + 1:02d}"
        books = {}
        for name in list(config.VARIANTS) + ["RAW"]:
            b = paper.Book(name, config.VARIANTS.get(name, config.TRIGGER), day)
            edge = 6.0 if name == "m2.5_s0.6" else -2.0
            b.trades = [{"pnl_pts": edge + (k % 3 - 1), "pnl_rs": 0, "advisors": {"room": {"veto": k % 4 == 0}},
                         "reason": "STOP", "time_in": "10:00:00"} for k in range(4)]
            books[name] = b
        learning.record_day(day, books)
        s = learning.learn(day)
    assert s["champion"] != config.CHAMPION_DEFAULT        # the losing champion was replaced
    assert os.path.exists(learning.REPORT)


def test_flow_orders_and_lead():
    """Order-count classes and the book-leads-price score: sellers' ORDERS pulled (not eaten)
    while price rises must read PULLED on the order series and give a positive run score."""
    from apex.engine.flow import Flow, PULL, CLS
    from apex.engine.market import Market
    import numpy as np
    from apex.table import ROW_DTYPE
    m = Market(); f = Flow(config.MAX_ROWS)
    snap = np.zeros(config.MAX_ROWS, dtype=ROW_DTYPE)
    i = 7
    for step in range(700):                                   # 70 s at 10 Hz
        t = step / 10.0
        snap = snap.copy()
        px = 100.0 + (max(0.0, t - 55.0) * 1.0)              # price runs in the last 15 s
        snap["ltp"][i] = px; snap["bid"][i] = px - 0.05; snap["ask"][i] = px + 0.05
        snap["ttq"][i] = 1000 + step * 2                      # a trickle of volume only
        sell_orders = 40 if t < 55 else max(5, 40 - int((t - 55) * 4))   # sellers cancel fast
        snap["bq"][i] = [500] * 5; snap["bo"][i] = [20] * 5
        snap["aq"][i] = [sell_orders * 25 / 5] * 5; snap["ao"][i] = [sell_orders / 5] * 5
        snap["depth_ns"][i] = 1; snap["tbq"][i] = 50000; snap["tsq"][i] = 30000
        m.push(snap, t); f.update(m, 0.1)
    assert CLS[int(f.cls_so[i])] in ("PULLED", "DRAIN-FAST"), CLS[int(f.cls_so[i])]
    assert f.imb_o[i] > 0.5 and f.imb_t[i] > 0.2
    assert f.run_score(i, 1, m) > 0.3
    assert -1 <= f.lead[i] <= 1


def test_straddle_watch_spike_and_roll():
    """The owner's straddle idea: pure theta decay is no spike; a directional move whose
    CE leg rises faster than theta while the PE falls is a SPIKE CE (gamma leg CE), the
    advisor vetoes a PE entry and accepts a CE one; after spot settles at the next
    strike the watch re-anchors and logs the roll."""
    from datetime import datetime, timedelta
    from apex.engine.straddle_watch import StraddleWatch
    w = StraddleWatch()
    t0, dt0, K = 1792380900.0, datetime(2026, 10, 19, 9, 15, tzinfo=config.IST), 25200
    g0 = {"CE": {"delta": 0.50, "gamma": 0.0021, "theta_min": -0.30}, "PE": {"delta": -0.50, "gamma": 0.0021, "theta_min": -0.30}}

    def step(t, ce, pe, atm=K, g=g0, fut=25200.0):
        w.update(t0 + t, dt0 + timedelta(seconds=t), atm,
                 {"CE": (ce, ce - .1, ce + .1), "PE": (pe, pe - .1, pe + .1)}, g, fut, 100.0)
    for t in range(600):                                      # 10 min of theta only
        step(t, 45.0 - 0.30 * t / 60, 45.0 - 0.30 * t / 60)
    assert w.spike is None and w.state in ("DECAYING", "FLAT"), w.state
    for t in range(600, 720):                                 # futures +40 in 2 min: CE +14, PE −8
        k = (t - 600) / 120
        g = {"CE": {"delta": 0.50 + 0.18 * k, "gamma": 0.0021, "theta_min": -0.30},
             "PE": {"delta": -0.50 + 0.18 * k, "gamma": 0.0019, "theta_min": -0.30}}
        step(t, 42.0 + 14 * k, 42.0 - 8 * k, g=g, fut=25200 + 40 * k)
    assert w.spike and w.spike["leg"] == "CE" and w.state == "SPIKE CE"
    assert w.legs["CE"]["ddelta"] > 0.03 and w.spike["fut_move"] > 0
    assert w.advise(-1)[0] is True and w.advise(+1)[0] is False
    assert w.drain_events()[0][0] == "SPIKE"
    for t in range(720, 1330):                                # spot settles one strike up
        step(t, 56.0, 34.0, atm=25250, fut=25240)
        if w.wants_roll():
            w.roll(t0 + t, dt0 + timedelta(seconds=t), 25250, {"CE": (40.0, 39.9, 40.1), "PE": (41.0, 40.9, 41.1)})
    assert w.K == 25250 and w.shifts[-1]["from"] == 25200 and w.spike is None
    assert w.drift_min is None and w.state == "WARMING"      # measured on the new strike only
    v = w.view()
    assert v["series"] and v["spikes"][0]["ended"] and "t_s" in v["spikes"][0]


def test_gex_map_regime_walls_flip():
    """Call-heavy chain -> DAMPEN with the call wall at the heavy strike; put-heavy -> AMPLIFY;
    heavy calls above and heavy puts below produce a flip level between them; the advisor vetoes
    chasing into a dampening regime and a close gamma wall."""
    from datetime import datetime
    from apex.engine.gex import GexMap
    now = datetime(2026, 10, 19, 10, 0, tzinfo=config.IST)
    F, ks = 25200.0, [25000 + 50 * i for i in range(9)]            # 25000 .. 25400
    def chain(ce, pe):
        return {str(k): {"call": c, "put": p} for k, c, p in zip(ks, ce, pe)}
    flat = [10000] * 9
    g = GexMap()
    calls = [10000] * 9; calls[6] = 90000                           # wall at 25300
    v = g.compute(chain(calls, flat), "2026-10-27", now, F, {}, 0.13)
    assert v["ok"] and v["regime"] == "DAMPEN" and v["balance"] > 0.1 and v["call_wall"] == 25300.0
    puts = [10000] * 9; puts[2] = 90000                             # heavy puts at 25100
    v2 = g.compute(chain(flat, puts), "2026-10-27", now, F, {}, 0.13)
    assert v2["regime"] == "AMPLIFY" and v2["balance"] < -0.1 and v2["put_wall"] == 25100.0
    both = g.compute(chain(calls, puts), "2026-10-27", now, F, {}, 0.13)
    assert both["flip"] is not None and 24900 < both["flip"] < 25500
    assert 25000 <= both["max_pain"] <= 25400
    g.v = v
    assert g.advise(+1, F)[0] is True                               # dampening, no flip ahead: do not chase
    assert g.advise(+1, 25290.0)[0] is True                         # 10 pts under a call wall: do not chase
    g.v = v2
    assert g.advise(+1, F)[0] is False                              # amplifying, calls flat -> no call wall
    assert v2["call_wall"] is None
    g.v = both                                                      # flip just ahead -> the escape applies
    if both["regime"] == "DAMPEN":
        side = 1 if both["flip"] > F else -1
        assert g.advise(side, both["flip"] - 10 * side)[0] is False
    assert g.compute({}, "2026-10-27", now, F, {}, 0.13)["ok"] is False


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
