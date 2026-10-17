"""
ApexOptions — configuration and the NSE calendar.

Everything tunable lives here. The four v1 trigger parameters are in TRIGGER;
the self-learning loop may switch the champion between pre-registered
VARIANTS, but never invents new numbers (see apex/engine/learning.py).
"""
import os
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# APEX_DATA lets sim / replay runs keep their paper books and learning state
# apart from the live paper account (run_apex.py sets data/sim, data/replay).
DATA_DIR = os.environ.get("APEX_DATA") or os.path.join(ROOT, "data")
TICKS_DIR = os.path.join(ROOT, "data", "ticks")    # recorder output (always the main data dir)
PAPER_DIR = os.path.join(DATA_DIR, "paper")        # paper books, trades csv
LEARN_DIR = os.path.join(DATA_DIR, "learning")     # self-learning state + reports
LOG_DIR = os.path.join(DATA_DIR, "logs")
SECRETS_DIR = os.path.join(ROOT, "secrets")        # gitignored; never committed
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
INSTRUMENTS_JSON = os.path.join(DATA_DIR, "instruments.json")
TOKEN_CACHE_JSON = os.path.join(ROOT, "data", "token_cache.json")

for _d in (DATA_DIR, TICKS_DIR, PAPER_DIR, LEARN_DIR, LOG_DIR, SECRETS_DIR):
    os.makedirs(_d, exist_ok=True)

# ── mode ─────────────────────────────────────────────────────────────────────
PAPER_ONLY = True          # v1 never places a broker order. Owner decision 17 Oct 2026.
AUDIO = True               # speaker alerts from the engine (armed / entry / win / loss), as in MYTHOS

# ── web ──────────────────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 8780                # MYTHOS uses 8765 — both can run side by side

# ── shared memory names ──────────────────────────────────────────────────────
SHM_TABLE = "apex_table_v1"
SHM_STATE = "apex_state_v1"
MAX_ROWS = 512
STATE_BYTES = 2 * 1024 * 1024

# ── instrument ───────────────────────────────────────────────────────────────
NIFTY = "NIFTY"
STRIKE_STEP = 50
LOT_SIZE = 65              # verified NSE contract master Oct–Dec 2026; re-check on lot revisions
FREEZE_QTY = 3510          # NSE/FAOP/76693 from 5 Oct 2026 (paper: informational)
WEEKLY_BAND = 12           # subscribe weekly ATM ± 12 strikes (both rights)
NEXTWEEK_BAND = 4          # next-week ATM ± 4 strikes
HERO_BAND = 2              # ATM ± 2 = the ten hero contracts (depth)
RECENTER_STRIKES = 4       # extend the bands when spot drifts this far (keeps next-week ±4 usable)

# ── session clock (IST) ──────────────────────────────────────────────────────
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
SUPPRESS_UNTIL = (9, 25)   # overnight repricing: synchrony meaningless (G1)
LAST_ENTRY = (15, 15)
FLATTEN_AT = (15, 25)
ZERO_DTE_FLATTEN = (15, 0) # 0DTE flat by 15:00 unless delta >= 0.9 (I-7)
ZERO_DTE_NO_ENTRY = (14, 45)
ZERO_DTE_NEXTWEEK_FROM = (13, 0)

# ── paper capital ────────────────────────────────────────────────────────────
START_CAPITAL = 100_000.0  # fresh every trading day [OWNER]
# Owner 17 Oct: paper trading — slippage and charges ignored. Fills at LTP, gross P&L.
# Bid/ask at fill are still recorded so a net view can be computed later.
FILL_AT = "ltp"

# ── v1 trigger (D-033): four tunables ────────────────────────────────────────
TRIGGER = {
    "m_star": 2.0,     # futures 15-s impulse z-score threshold
    "s_star": 0.50,    # weighted basket synchrony threshold
    "L_star": 3.0,     # not-late: futures move since onset <= L* x sigma15
    "d_star": 12.0,    # stop distance in Nifty-futures points (also the trail width; 1R)
}
IV_RISE_CAP = 1.5      # vol points since onset (frozen, not tuned — G2/G7)
ONSET_Z = 1.0          # |z| at which an episode starts
EPISODE_END_Z = 0.5    # episode ends after |z| < this for EPISODE_END_SEC
EPISODE_END_SEC = 30.0
RECRUIT_Z = 1.0        # a stock counts toward synchrony at |z_i| >= this
ACTIVITY_MIN = 1.2     # ...and volume >= this x its own baseline (once warm)
SIGMA_HALF_LIFE_S = 20 * 60
SIGMA15_SEED = 4.0     # Nifty pts; used until the 20-min scale warms up
WARMUP_S = 10 * 60

# Pre-registered variants for the self-learning loop (registered 17 Oct 2026).
# Every variant trades its own virtual paper book in parallel on the same data;
# the champion's book is the one shown as "the" paper account.
VARIANTS = {
    f"m{m}_s{s}": {"m_star": m, "s_star": s, "L_star": 3.0, "d_star": 12.0}
    for m in (1.5, 2.0, 2.5) for s in (0.4, 0.5, 0.6)
}
# Owner's purest domino idea (17 Oct): enter when the heavyweight BASKET implies a move the
# futures have not yet made — gap = basket-implied pts − futures pts ≥ gap_star, with synchrony.
VARIANTS["gap3_s0.4"] = {"m_star": 1.0, "s_star": 0.4, "L_star": 3.0, "d_star": 12.0, "gap_star": 3.0}
VARIANTS["gap5_s0.4"] = {"m_star": 1.0, "s_star": 0.4, "L_star": 3.0, "d_star": 12.0, "gap_star": 5.0}
# Fifth exit as a variant: leave when the sellers on the HELD contract refill (orders and
# quantity) while futures stall — "force on the contract you hold".
VARIANTS["m2.0_s0.5_bookexit"] = {"m_star": 2.0, "s_star": 0.5, "L_star": 3.0, "d_star": 12.0, "exit_book": True}
# Owner's straddle observation (17 Oct, evening): when the fixed-strike ATM straddle spikes above
# its theta decay, buy the leg that carries the spike (its delta is rising). One trade per spike,
# entered within SPIKE_ENTRY_MAX_AGE_S of the spike's start; the usual four exits apply.
VARIANTS["straddle_spike"] = {"m_star": 2.0, "s_star": 0.5, "L_star": 3.0, "d_star": 12.0, "spike": True}
CHAMPION_DEFAULT = "m2.0_s0.5"

# ── straddle watch (apex/engine/straddle_watch.py) ───────────────────────────
SPIKE_MIN_PTS = 4.0        # excess over theta in 5 min, premium points — the floor
SPIKE_MIN_FRAC = 0.06      # ...or 6 % of the straddle 5 min ago, whichever is larger
SPIKE_SIGMA = 2.5          # ...or 2.5 x the running scale of |excess| in quiet time (20-min half-life)
SPIKE_SIGMA_SEED = 1.5     # premium points, until the scale warms up
SPIKE_COOLDOWN_S = 90.0    # after a spike ends, the next one needs this much quiet first
SPIKE_ENTRY_MAX_AGE_S = 150.0   # the straddle_spike book only enters this soon after a spike starts
SPIKE_MIN_DDELTA = 0.03    # ...and only if the leg's |delta| rose at least this much over 5 min

# Owner-maintained event calendar: days when the index moves on news, not on the heavyweights.
# Logged as a would-veto advisor ("event"); becomes a rule only through the learning loop.
EVENT_DAYS = {
    # "2026-12-05": "RBI policy",
}

# ── instrument choice (G4 delta bands, v1 rule: nearest-the-money in band) ──
DELTA_BANDS = {           # by days-to-expiry bucket
    "ge3": (0.52, 0.70),
    "1to2": (0.60, 0.80),
    "zero_am": (0.65, 0.85),
    "nextweek": (0.52, 0.65),
}
MIN_PREMIUM = 20.0
MAX_PREMIUM = 600.0

# ── REST budget (ICICI: 100/min and 5,000/day across all endpoints) ─────────
CHAIN_POLL_S = 90.0
VIX_POLL_S = 60.0
REST_DAY_BUDGET = 5000
REST_DAY_DATA_CAP = 3000

# ── NSE holiday calendar (weekday closures) — drives expiry shifts ───────────
NSE_HOLIDAYS = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24",
    "2026-12-25",
}
NSE_HOLIDAYS_EXTRA = set()  # add ad-hoc closures here as "YYYY-MM-DD"

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    iso = d.isoformat()
    return iso not in NSE_HOLIDAYS and iso not in NSE_HOLIDAYS_EXTRA


def _roll_back(d: date) -> date:
    for _ in range(10):
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return d


def _after_close(now: datetime) -> bool:
    return now.hour * 60 + now.minute >= 15 * 60 + 30


def weekly_expiries(now: datetime, n: int = 2) -> list:
    """Next n live weekly Nifty expiries (Tuesday, holiday-shifted to the previous
    trading day; today's expiry rolls off after 15:30)."""
    today = now.date()
    t = today + timedelta(days=(1 - today.weekday()) % 7)
    out = []
    for _ in range(20):
        e = _roll_back(t)
        if e > today or (e == today and not _after_close(now)):
            if not out or out[-1] != e:
                out.append(e)
        if len(out) >= n:
            break
        t += timedelta(days=7)
    return out


def _last_tuesday(y: int, m: int) -> date:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != 1:
        d -= timedelta(days=1)
    return d


def monthly_expiry(now: datetime) -> date:
    """Near-month futures expiry: last Tuesday of the month, holiday-shifted."""
    today = now.date()
    y, m = today.year, today.month
    for _ in range(3):
        e = _roll_back(_last_tuesday(y, m))
        if e > today or (e == today and not _after_close(now)):
            return e
        y, m = (y + (m == 12), m % 12 + 1)
    return e


def monthly_expiry_candidates(now: datetime) -> list:
    """Stock futures: last Tuesday (current NSE rule) with last Thursday as a
    fallback probe — the token lookup decides which one exists."""
    e = monthly_expiry(now)
    y, m = e.year, e.month
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != 3:
        d -= timedelta(days=1)
    thu = _roll_back(d)
    return [e] if thu == e else [e, thu]


def ws_expiry(d: date) -> str:
    """Breeze websocket/token expiry format, locale-independent: 19-Oct-2026."""
    return f"{d.day:02d}-{_MONTHS[d.month]}-{d.year}"


def rest_expiry(d: date) -> str:
    return f"{d.isoformat()}T06:00:00.000Z"


def now_ist() -> datetime:
    return datetime.now(IST)


def hm(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def mins(t) -> int:
    return t[0] * 60 + t[1]
