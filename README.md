# ApexOptions

A Nifty weekly options **buying** system for one trader — Nifty only, buy only (CE or PE, never sell), ₹1,00,000 a day, all-in every trade, profits compounded into the next trade.

**Status (17 Oct 2026): v1 built — PAPER TRADING ONLY.** It watches the market tick by tick, takes trades on paper, and tells you each one. No order is ever sent to ICICI. Slippage and charges are ignored (fills at LTP, gross). No static IP needed.

## Run it

One-time setup (Windows, in `D:\ApexOptions`):

```
pip install -r requirements.txt
```

Try it right now, no login needed — a synthetic market at 10× speed:

```
python run_apex.py sim
```

Every trading morning, live data:

```
python run_apex.py session --profile p2     # paste today's session token (once a day)
python run_apex.py preflight --profile p2   # must say GO
python run_apex.py live --profile p2        # opens http://127.0.0.1:8780
```

`--profile p2` reads `secrets\breeze_p2.json` — use your **second** API key here and leave the first to MYTHOS (see below). Without `--profile` it uses `secrets\breeze.json`. The `session` command asks for the key and secret the first time and stores them only in `secrets\` (gitignored, never committed).

Other commands:

| Command | What it does |
|---|---|
| `python run_apex.py replay data\ticks\2026-10-19.jsonl.gz --speed 20` | replay a recorded live day through the same code |
| `python run_apex.py sim --days 3 --speed 10 --record` | several synthetic days back to back (shows the learning loop working) |
| `python run_apex.py report` | today's paper trades (CSV) and the learning report |
| `python run_apex.py learn` | re-run the after-close learning step by hand |

Ctrl+C stops everything cleanly; books are saved continuously.

## What you see on the dashboard

- **Header** — clock, feed state, Nifty / futures / VIX / ATM IV (and its 5-min change), tick age, hot-path time per packet, messages per second, paper capital and the day's P&L.
- **Ladder** — the ten hero contracts (weekly ATM ± 2, CE and PE), updated on every tick: LTP (flashes green/red), bid/ask, Δ, IV, volume per second, OI change, standing **buyers** and **sellers** as quantity (the tug bar) AND as number of orders, each with its rate class — REFILLING, HOLDING, DRAIN-SLOW, DRAIN-FAST, **PULLED** (sellers leaving, not being eaten) — plus the contract's **book→price** score (does its book lead its price right now). The header shows the ATM straddle against its VWAP (premium being bought or sold).
- **Trigger** — futures impulse z, basket synchrony up/down against the thresholds, the current episode (who moved first, how many heavyweights crossed, how old, IV since onset), the exact reason the champion is or isn't trading, and five advisors' would-veto verdicts.
- **Heavyweights** — every tracked stock's 15-second move converted into Nifty points, its z-score and volume vs its own baseline; the first mover is outlined.
- **Pressure & force** — CE walls (resistance) and PE walls (support) from the chain, room to the next wall, and the force detector on the futures book at the nearest level (VACUUM / BREAK-IMMINENT / WEAKENING / HOLD-STRONG …).
- **Straddle watch** — a FIXED strike's CE+PE (the live ATM re-centres and makes the usual straddle chart jump): the straddle against the path theta alone would have given it, its VWAP, every spike (gold) and every ATM roll (blue). A spike is the straddle gaining more than theta allows in 5 minutes with one leg carrying it — that leg (rising delta, moving faster than theta) is the **gamma leg**, shown with its delta change, gamma and 1-minute acceleration. Today's spikes are listed with what the leg and the futures did afterwards; each one is also written to `data/paper/straddle_DAY.jsonl` with +1/+5/+10 min outcomes. Advisor `gamma_leg` and the paper book `straddle_spike` trade the idea on paper (D-060 / D-061).
- **Dealer gamma map** — under the open-interest map: whether option-dealer hedging should dampen or amplify moves (balance), the gamma flip level, the call and put gamma walls and max pain, from the chain's open interest. It assumes dealers are long calls and short puts, which may be wrong on Nifty, so it is evidence only: advisor `gex_room` is logged on every trade and earns a vote only through the learning loop (D-062).
- **Paper position, trades, capital** — live P&L of the open paper trade, the futures stop, every closed trade with its exit reason and the capital after it.
- **Self-learning** — the ten parallel paper books and the scoreboard. Sound on entries and exits (🔈 button).

## How it improves itself (decisions D-050 / D-051)

"Shadow testing" here means: ten paper books trade the same ticks at the same time — nine pre-registered variants of the trigger and RAW (the champion with no extra gates). The champion's book is your paper account. After every close the learning step:

1. runs the sequential test on the champion (GO / KILL lines),
2. replaces the champion only when a challenger beats it over ≥ 10 days with t ≥ 2.5 and survives leave-one-day-out, or when the champion hits KILL,
3. promotes an advisor to a hard gate only when removing the trades it would have vetoed improves results by ≥ 1 pt/trade without killing the big winners — and demotes it if that stops being true.

Changes take effect the next morning, never mid-session, and it never invents new numbers. The report is in `data\learning\report.md`.

## API keys — read before Monday

ApexOptions and MYTHOS can share one API key for data, but one key means one daily session and one websocket session: two programs on it can knock each other's subscriptions off and share the 100-per-minute / 5,000-per-day REST limit. **Use your second API key for ApexOptions** (`--profile p2`).

## Layout

```
run_apex.py            supervisor and commands
apex/config.py         every tunable, the NSE calendar (holidays, expiry shifts)
apex/universe.py       heavyweights and index weights (NSE factsheets, 30 Sep 2026)
apex/feed_breeze.py    live Breeze feed (raw packets, recorder, VIX + chain polling)
apex/feed_sim.py       synthetic market        apex/feed_replay.py   recorded-day replay
apex/feed_core.py      the one packet parser    apex/table.py         shared-memory table
apex/engine_main.py    engine loop              apex/engine/          flow, domino, levels, paper, learning
apex/greeks.py         Black-76, IV, Greeks     apex/gateway.py + static/   dashboard
data/                  ticks, paper books, trades CSVs, learning state, logs (gitignored)
secrets/               credentials only (gitignored)
docs/                  the design: master design, decision log (D-001…D-053), open questions, team memos
tests/test_core.py     offline checks:  python tests\test_core.py
```

## House rules
- No credentials in any file in this tree, ever (preflight fails if it finds one).
- Sim results say the plumbing works — nothing about edge. Only live paper sessions count.
