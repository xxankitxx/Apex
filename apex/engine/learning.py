"""
Self-improvement loop — it gets better on evidence, never on one lucky day.

Every session, nine PRE-REGISTERED variants of the v1 trigger (config.VARIANTS)
trade their own paper books on identical data. One is the CHAMPION — its book
is the paper account you watch. A tenth book, RAW, is the champion without any
promoted gates, so every advisor's would-have verdict can always be scored.

After the close (engine day-roll or `python run_apex.py learn`):
 1. Scoreboard: a sequential test (Wald SPRT) on the champion's per-trade points
    since it became champion:  GO when Σx >= 66.5 + 0.75n,  KILL when
    Σx <= -37.4 + 0.75n  (H0 mean <= 0 vs H1 mean >= +1.5 pts, alpha 5%, beta 20%,
    sigma 6). Undecided after 200 trades = treated as KILL.
 2. Champion replacement: a challenger replaces the champion only if, over
    >= 10 sessions both have traded since the champion took over, its daily
    P&L beats the champion's with mean > 0, t-stat >= 2.5 (strict, because
    eight challengers are compared), AND every leave-one-day-out mean > 0.
    If the champion hits KILL, the best challenger that is not itself in KILL
    territory takes over and the scoreboard restarts.
 3. Advisor promotion: an advisor (IV-late, room-to-wall, coherence, force,
    episode-type) becomes a GATE only if, on RAW's trades since registration:
    >= 30 trades and >= 8 vetoed; removing the vetoed trades improves the mean
    by >= 1 pt/trade; it would have vetoed <= 25% of the top-quartile winners;
    and the improvement survives leave-one-day-out. A promoted gate is demoted
    if its rolling score on later RAW trades turns negative.
Nothing here invents new parameters; it only chooses among registered ones.
Decisions are written to data/learning/state.json and report.md, and take
effect at the next session (never intraday — invariant I-11).
"""
import json
import math
import os
from collections import defaultdict
from datetime import date

from .. import config

STATE = os.path.join(config.LEARN_DIR, "state.json")
DAYS = os.path.join(config.LEARN_DIR, "days.jsonl")
REPORT = os.path.join(config.LEARN_DIR, "report.md")
ADVISORS = ["iv_late", "room", "coherence", "force", "episode", "book", "premium", "quiet", "bank", "event", "gamma_leg", "gex_room"]
REGISTERED = "2026-10-17"


def sprt_lines(n):
    return 66.5 + 0.75 * n, -37.4 + 0.75 * n


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"registered": REGISTERED, "champion": config.CHAMPION_DEFAULT,
                "champion_since": REGISTERED, "gates": [], "retired": [], "log": [],
                "status": "COLLECTING"}


def save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


def already_learned(day):
    s = load_state()
    return s.get("learned_day") == day


def record_day(day, books):
    """Append the finished day's trades for every book to days.jsonl (idempotent per day)."""
    rows = []
    if os.path.exists(DAYS):
        with open(DAYS) as f:
            rows = [json.loads(x) for x in f if x.strip()]
    rows = [r for r in rows if r["day"] != day]
    for name, b in books.items():
        rows.append({"day": day, "book": name,
                     "trades": [{"pnl_pts": t["pnl_pts"], "pnl_rs": t["pnl_rs"],
                                 "advisors": {k: bool(v.get("veto")) for k, v in (t.get("advisors") or {}).items()},
                                 "reason": t["reason"], "time_in": t["time_in"]} for t in b.trades]})
    rows.sort(key=lambda r: (r["day"], r["book"]))
    with open(DAYS, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _load_days():
    out = defaultdict(dict)       # book -> day -> [trades]
    if not os.path.exists(DAYS):
        return out
    with open(DAYS) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["book"]][r["day"]] = r["trades"]
    return out


def _mean(x):
    return sum(x) / len(x) if x else 0.0


def _t(x):
    n = len(x)
    if n < 2:
        return 0.0
    m = _mean(x)
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd > 0 else (math.inf if m > 0 else 0.0)


def _lodo_ok(day_vals):
    if len(day_vals) < 3:
        return False
    tot = sum(day_vals)
    n = len(day_vals)
    return all((tot - v) / (n - 1) > 0 for v in day_vals)


def learn(today: str = None):
    s = load_state()
    days = _load_days()
    lines = [f"# ApexOptions — learning report ({today or date.today().isoformat()})", ""]
    champ = s["champion"]

    # 1. scoreboard for the champion
    ctr = [t["pnl_pts"] for d, tr in sorted(days.get(champ, {}).items()) if d >= s["champion_since"] for t in tr]
    n, tot = len(ctr), sum(ctr)
    go, kill = sprt_lines(n)
    if n and tot >= go:
        status = "GO — edge > 0 is now likely (size still uncertain)"
    elif n and (tot <= kill or n >= 200):
        status = "KILL — champion retired"
    else:
        status = "COLLECTING"
    s["scoreboard"] = {"n": n, "sum": round(tot, 2), "go_line": round(go, 1), "kill_line": round(kill, 1)}
    lines += [f"## Scoreboard — champion `{champ}`",
              f"{n} trades since {s['champion_since']}, Σ {tot:+.1f} pts. GO line {go:.1f}, KILL line {kill:.1f} → **{status}**", ""]

    # 2. champion vs challengers (paired daily P&L since the champion took over)
    def daily(book):
        return {d: sum(t["pnl_pts"] for t in tr) for d, tr in days.get(book, {}).items() if d >= s["champion_since"]}

    cd = daily(champ)
    best, best_t = None, 0.0
    lines += ["## Challengers (daily points vs champion, since it took over)", "",
              "| variant | days | mean diff/day | t | LODO | total pts |", "|---|---|---|---|---|---|"]
    for v in config.VARIANTS:
        if v == champ or v in s["retired"]:
            continue
        vd = daily(v)
        common = sorted(set(cd) & set(vd))
        diff = [vd[d] - cd[d] for d in common]
        t = _t(diff)
        lodo = _lodo_ok(diff)
        lines.append(f"| {v} | {len(common)} | {_mean(diff):+.2f} | {t:.2f} | {'yes' if lodo else 'no'} | {sum(vd.values()):+.1f} |")
        if len(common) >= 10 and _mean(diff) > 0 and t >= 2.5 and lodo and t > best_t:
            best, best_t = v, t
    lines.append("")
    change = None
    if status.startswith("KILL"):
        s["retired"].append(champ)
        alive = []
        for v in config.VARIANTS:
            if v in s["retired"]:
                continue
            x = [t["pnl_pts"] for tr in days.get(v, {}).values() for t in tr]
            g, k = sprt_lines(len(x))
            if not x or sum(x) > k:
                alive.append((sum(x), v))
        if alive:
            change = max(alive)[1]
            lines.append(f"Champion `{champ}` hit KILL → replaced by `{change}` (best surviving record). Scoreboard restarts.")
        else:
            lines.append("**Every registered variant is in KILL territory: the v1 hypothesis has no edge. "
                         "Paper trading continues for data, but a new hypothesis is needed (owner decision).**")
            s["status"] = "NO-EDGE"
    elif best:
        change = best
        lines.append(f"Challenger `{best}` beat the champion (t {best_t:.2f}, LODO ok) → promoted.")
    if change:
        s["log"].append({"day": today, "event": "champion", "from": champ, "to": change})
        s["champion"], s["champion_since"] = change, (today or date.today().isoformat())
        s["scoreboard"] = {"n": 0, "sum": 0.0, "go_line": 66.5, "kill_line": -37.4}

    # 3. advisors on RAW
    raw = [(d, t) for d, tr in sorted(days.get("RAW", {}).items()) if d >= s["registered"] for t in tr]
    lines += ["", "## Advisors (would-have vetoes on the ungated champion)", "",
              "| advisor | trades | vetoed | mean all | mean kept | gain/trade | top-winners vetoed | LODO | status |",
              "|---|---|---|---|---|---|---|---|---|"]
    pts = sorted([t["pnl_pts"] for _, t in raw])
    q75 = pts[int(0.75 * (len(pts) - 1))] if pts else 0
    for a in ADVISORS:
        vet = [(d, t) for d, t in raw if t["advisors"].get(a)]
        kept = [(d, t) for d, t in raw if not t["advisors"].get(a)]
        m_all = _mean([t["pnl_pts"] for _, t in raw])
        m_kept = _mean([t["pnl_pts"] for _, t in kept])
        gain = m_kept - m_all
        top = [t for _, t in raw if t["pnl_pts"] >= q75 and t["pnl_pts"] > 0]
        top_v = sum(1 for t in top if t["advisors"].get(a)) / len(top) if top else 0.0
        byday = defaultdict(float)
        for d, t in vet:
            byday[d] -= t["pnl_pts"]           # removing a vetoed trade adds -pnl
        lodo = _lodo_ok(list(byday.values())) if byday else False
        ok = len(raw) >= 30 and len(vet) >= 8 and gain >= 1.0 and top_v <= 0.25 and lodo
        was = a in s["gates"]
        if ok and not was:
            s["gates"].append(a)
            s["log"].append({"day": today, "event": "gate+", "advisor": a})
            st = "PROMOTED"
        elif was and len(raw) >= 30 and gain < 0:
            s["gates"].remove(a)
            s["log"].append({"day": today, "event": "gate-", "advisor": a})
            st = "DEMOTED"
        else:
            st = "GATE" if was else "advisory"
        lines.append(f"| {a} | {len(raw)} | {len(vet)} | {m_all:+.2f} | {m_kept:+.2f} | {gain:+.2f} | "
                     f"{top_v:.0%} | {'yes' if lodo else 'no'} | {st} |")
    s["status"] = s.get("status") if s.get("status") == "NO-EDGE" else status.split(" ")[0]
    s["learned_day"] = today
    lines += ["", f"Champion for the next session: **`{s['champion']}`** · gates: {', '.join(s['gates']) or 'none'}"]
    save_state(s)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return s
