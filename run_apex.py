"""
ApexOptions — one entry point.  PAPER TRADING ONLY: no order is ever sent.

  python run_apex.py session  [--profile p2]     save today's Breeze session token (once a day)
  python run_apex.py preflight [--profile p2]    checks before the open: GO / NO-GO
  python run_apex.py live     [--profile p2]     live data from Breeze, paper trades
  python run_apex.py sim      [--speed 10] [--days 1] [--seed 7] [--record]
                                                 synthetic market, no login (try it now)
  python run_apex.py replay data/ticks/2026-10-19.jsonl.gz [--speed 10]
  python run_apex.py learn                       re-run the after-close learning step
  python run_apex.py report                      print today's paper trades + learning report

Dashboard: http://127.0.0.1:8780   (MYTHOS keeps 8765; both can run together)

The supervisor creates the shared memory, starts FEED, ENGINE and GATEWAY as
separate processes, restarts the live feed if it dies, and on Ctrl+C asks
everything to stop cleanly (books are saved, the day is learned after the close).
Sim and replay keep their paper books and learning state in data/sim and
data/replay, so they never touch the live paper account's record.
"""
import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def data_dir_for(mode):
    if mode == "live":
        return os.path.join(ROOT, "data")
    return os.path.join(ROOT, "data", mode)


def child_env(mode):
    env = dict(os.environ)
    env["APEX_DATA"] = data_dir_for(mode)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def spawn(module, args, mode):
    return subprocess.Popen([sys.executable, "-m", module] + args, cwd=ROOT, env=child_env(mode))


def supervise(mode, feed_args, speed=1.0, open_browser=True):
    os.environ["APEX_DATA"] = data_dir_for(mode)
    from apex import config
    from apex.table import StateBlob, Table
    if port_busy(config.PORT):
        sys.exit(f"Port {config.PORT} is busy — is another ApexOptions running?")
    try:
        t = Table(create=True)
        b = StateBlob(create=True)
    except FileExistsError:
        sys.exit("Another ApexOptions process still holds the shared memory — close the old console (Task Manager: python.exe) and retry.")
    t.set("speed", speed)
    feed_mod = {"live": "apex.feed_breeze", "sim": "apex.feed_sim", "replay": "apex.feed_replay"}[mode]
    procs = {
        "feed": spawn(feed_mod, feed_args, mode),
        "engine": spawn("apex.engine_main", [mode], mode),
        "gateway": spawn("apex.gateway", [], mode),
    }
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"\n  ApexOptions [{mode.upper()} · PAPER]  dashboard: {url}\n  Ctrl+C to stop.\n", flush=True)
    if open_browser:
        time.sleep(1.5)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    restarts = 0
    try:
        while True:
            time.sleep(1.0)
            if procs["engine"].poll() is not None:
                if mode == "live":
                    print("ENGINE exited — restarting (books are on disk)", flush=True)
                    procs["engine"] = spawn("apex.engine_main", [mode], mode)
                else:
                    break                       # sim/replay finished and learned
            if procs["gateway"].poll() is not None:
                procs["gateway"] = spawn("apex.gateway", [], mode)
            if procs["feed"].poll() is not None and mode == "live":
                restarts += 1
                if restarts > 20:
                    print("FEED keeps dying — see data/logs/feed.log", flush=True)
                    time.sleep(30)
                print(f"FEED exited (code {procs['feed'].returncode}) — restarting", flush=True)
                time.sleep(min(5 * restarts, 60))
                procs["feed"] = spawn(feed_mod, feed_args, mode)
    except KeyboardInterrupt:
        print("\nstopping…", flush=True)
    finally:
        t.set("stop", 1)
        deadline = time.time() + 12
        for name in ("feed", "engine", "gateway"):
            p = procs[name]
            while p.poll() is None and time.time() < deadline and name != "gateway":
                time.sleep(0.2)
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        t.close(); b.close(); t.unlink(); b.unlink()
        print(f"stopped. Paper books: {os.path.join(data_dir_for(mode), 'paper')}", flush=True)


def port_busy(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


# ── session ────────────────────────────────────────────────────────────────
def cmd_session(profile):
    from apex import config
    name = f"breeze_{profile}.json" if profile else "breeze.json"
    path = os.path.join(config.SECRETS_DIR, name)
    c = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    if not c.get("api_key"):
        c["api_key"] = getpass.getpass("Breeze API key (hidden): ").strip()
        c["api_secret"] = getpass.getpass("Breeze API secret (hidden): ").strip()
    login = "https://api.icicidirect.com/apiuser/login?api_key=" + urllib.parse.quote_plus(c["api_key"])
    print("\nLog in here (the browser opens it), then copy the API_Session value from the address bar:\n  " + login)
    try:
        webbrowser.open(login)
    except Exception:
        pass
    tok = input("\nSession token: ").strip()
    m = re.search(r"apisession=(\w+)", tok, re.I)
    c["session_token"] = m.group(1) if m else tok
    os.makedirs(config.SECRETS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f)
    print(f"saved to {path} (gitignored, never committed). Now: python run_apex.py preflight"
          + (f" --profile {profile}" if profile else ""))


# ── preflight ──────────────────────────────────────────────────────────────
KEYLIKE = re.compile(r"(api_?key|api_?secret|session_?token)\s*[=:]\s*['\"][A-Za-z0-9~!@#$%^&*()_+\-]{8,}['\"]", re.I)
# obvious stand-ins quoted in docs/research notes (e.g. api_key="sk-no-key-required") are not leaks
PLACEHOLDER = re.compile(r"no-?key|your[_-]?|xxx|example|placeholder|dummy|change ?me|sample|redacted|<[^>]*>|\.\.\.", re.I)


def cmd_preflight(profile):
    from apex import config
    res = []

    def check(name, ok, note=""):
        res.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + note) if note else ''}")

    print("ApexOptions preflight (paper mode)\n")
    # wsproto: the gateway's websocket backend (uvicorn ws="wsproto"); truststore: Windows-store
    # TLS trust for the live stream.  Both are in requirements.txt; a missing one is a real FAIL
    # (an earlier version printed PASS for a missing truststore, which hid the problem).
    for mod in ("numpy", "fastapi", "uvicorn", "wsproto", "breeze_connect", "truststore"):
        try:
            __import__(mod)
            check(f"python package {mod}", True)
        except Exception:
            check(f"python package {mod}", False, f"pip install {mod}   (or: pip install -r requirements.txt)")
    now = config.now_ist()
    check("NSE holiday calendar covers this year", any(h.startswith(str(now.year)) for h in config.NSE_HOLIDAYS),
          "add next year's holidays to config.NSE_HOLIDAYS")
    w = config.weekly_expiries(now, 2)
    check("weekly expiries", len(w) == 2, f"{w[0]} and {w[1]}" if len(w) == 2 else "")
    leaks = []
    for dp, dn, fn in os.walk(ROOT):
        if any(x in dp for x in ("secrets", os.sep + "data", ".git", "__pycache__")):
            continue
        for f in fn:
            if f.endswith((".py", ".md", ".json", ".js", ".html", ".txt", ".cfg", ".ini")):
                try:
                    text = open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read()
                    if any(not PLACEHOLDER.search(m.group(0)) for m in KEYLIKE.finditer(text)):
                        leaks.append(f)
                except Exception:
                    pass
    check("no credential-shaped strings outside secrets/", not leaks, ", ".join(leaks))
    gi = os.path.join(ROOT, ".gitignore")
    check(".gitignore excludes secrets/ and data/", os.path.exists(gi) and "secrets" in open(gi).read())
    check(f"port {config.PORT} free", not port_busy(config.PORT))
    trust = "n/a"
    try:
        from apex.feed_breeze import install_trust
        trust = install_trust()
    except Exception as e:
        trust = str(e)
    # (the fallback text mentions 'truststore' too — test the prefix, not a substring)
    check("TLS trust", trust.startswith("truststore"), trust)
    for host in ("api.icicidirect.com", "livestream.icicidirect.com"):
        try:
            import ssl
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=6) as s:
                with ctx.wrap_socket(s, server_hostname=host):
                    pass
            check(f"TLS handshake {host}", True)
        except Exception as e:
            check(f"TLS handshake {host}", False, str(e)[:120])
    try:
        from apex.feed_breeze import load_credentials
        c = load_credentials(profile)
        check("credentials file", True, "secrets/" + (f"breeze_{profile}.json" if profile else "breeze.json"))
        br = None
        try:
            from breeze_connect import BreezeConnect
            br = BreezeConnect(api_key=c["api_key"])
            br.generate_session(api_secret=c["api_secret"], session_token=c["session_token"])
            check("Breeze session valid today", True)
        except Exception as e:
            check("Breeze session valid today", False, f"{str(e)[:100]} — run: python run_apex.py session")
        if br is not None:
            # the contracts the feed must resolve offline (the SDK returns '4.1!False' for unknown ones)
            br.interval = ""
            w0 = config.weekly_expiries(now, 1)[0]
            mexp = config.monthly_expiry(now)
            probes = [("NIFTY index", dict(exchange_code="NSE", stock_code="NIFTY")),
                      ("NIFTY futures " + config.ws_expiry(mexp), dict(exchange_code="NFO", stock_code="NIFTY", product_type="futures", expiry_date=config.ws_expiry(mexp))),
                      ("HDFC Bank cash (HDFBAN)", dict(exchange_code="NSE", stock_code="HDFBAN"))]
            spot = 0.0
            try:
                r = br.get_quotes(stock_code="NIFTY", exchange_code="NSE", product_type="cash", expiry_date="", right="", strike_price="")
                rows = (r or {}).get("Success") or []
                spot = float(rows[0].get("ltp") or 0) or float(rows[0].get("previous_close") or 0) if rows else 0.0
            except Exception:
                pass
            check("NIFTY quote by REST", spot > 0, f"{spot:.1f}" if spot else "no ltp/previous_close in response")
            if spot > 0:
                atm = round(spot / config.STRIKE_STEP) * config.STRIKE_STEP
                probes.append((f"NIFTY {int(atm)} CE {config.ws_expiry(w0)}",
                               dict(exchange_code="NFO", stock_code="NIFTY", product_type="options", expiry_date=config.ws_expiry(w0), strike_price=str(int(atm)), right="call")))
            for name, kw in probes:
                try:
                    r = br.get_stock_token_value(get_exchange_quotes=True, get_market_depth=False, **kw)
                    ok = isinstance(r, tuple) and r[0] and "False" not in str(r[0])
                    check(f"token: {name}", bool(ok), str(r[0]) if ok else f"not in the security master ({str(r)[:60]})")
                except Exception as e:
                    check(f"token: {name}", False, str(e)[:80])
            # The SDK's ws_connect() reports every failure as 'Failed to connect to live stream'.
            # Do the same handshake in two visible steps instead, keeping the real error text.
            from apex.feed_breeze import connect_stream, drop_stream, stream_hint, stream_probe, stream_versions
            try:
                check("stream libraries", True, stream_versions())
            except Exception as e:
                check("stream libraries", False, str(e)[:120])
            proxies = sorted(k for k in os.environ if k.lower() in ("https_proxy", "http_proxy", "all_proxy", "wss_proxy"))
            if proxies:
                print(f"         note: proxy variables set ({', '.join(proxies)}) — the websocket goes through that proxy too")
            try:
                ok, det = stream_probe()
            except Exception as e:
                ok, det = False, f"{type(e).__name__}: {str(e)[:140]}"
            hint = stream_hint(det) if not ok else ""
            check("livestream engine.io handshake (raw websocket)", ok, det + (f" → {hint}" if hint else ""))
            if ok:
                try:
                    connect_stream(br)
                    check("websocket connect + auth (livestream)", True)
                except Exception as e:
                    det = str(e)[:160]
                    hint = stream_hint(det)
                    check("websocket connect + auth (livestream)", False, det + (f" → {hint}" if hint else ""))
                finally:
                    drop_stream(br)
            else:
                check("websocket connect + auth (livestream)", False, "skipped — the raw handshake above failed first")
    except SystemExit as e:
        check("credentials file", False, str(e))
    ok = all(res)
    go = "GO — start with:  python run_apex.py live" + (f" --profile {profile}" if profile else "")
    print("\n  " + (go if ok else "NO-GO — fix the FAIL lines above"))
    return ok


def cmd_learn(mode):
    os.environ["APEX_DATA"] = data_dir_for(mode)
    from apex import config
    from apex.engine import learning
    s = learning.learn(config.now_ist().date().isoformat())
    print(open(learning.REPORT, encoding="utf-8").read())
    return s


def cmd_report(mode):
    os.environ["APEX_DATA"] = data_dir_for(mode)
    from apex import config
    from apex.engine import learning
    paper = os.path.join(config.DATA_DIR, "paper")
    files = sorted(f for f in os.listdir(paper) if f.startswith("trades_")) if os.path.isdir(paper) else []
    if files:
        print(f"== {files[-1]} ==")
        print(open(os.path.join(paper, files[-1]), encoding="utf-8").read())
    if os.path.exists(learning.REPORT):
        print(open(learning.REPORT, encoding="utf-8").read())


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="ApexOptions (paper trading)")
    ap.add_argument("cmd", choices=["live", "sim", "replay", "session", "preflight", "learn", "report"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--profile", default="", help="second Breeze account: secrets/breeze_<profile>.json")
    ap.add_argument("--speed", type=float, default=10.0)
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--mode", default="live", help="for learn/report: live | sim | replay")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.cmd == "session":
        cmd_session(a.profile)
    elif a.cmd == "preflight":
        sys.exit(0 if cmd_preflight(a.profile) else 1)
    elif a.cmd == "learn":
        cmd_learn(a.mode)
    elif a.cmd == "report":
        cmd_report(a.mode)
    elif a.cmd == "live":
        supervise("live", [a.profile] if a.profile else [], 1.0, not a.no_browser)
    elif a.cmd == "sim":
        args = ["--speed", str(a.speed), "--days", str(a.days), "--seed", str(a.seed)] + (["--record"] if a.record else [])
        supervise("sim", args, a.speed, not a.no_browser)
    elif a.cmd == "replay":
        if not a.file or not os.path.exists(a.file):
            sys.exit("replay needs a recorded file, e.g. data/ticks/2026-10-19.jsonl.gz")
        supervise("replay", [os.path.abspath(a.file), "--speed", str(a.speed)], a.speed, not a.no_browser)


if __name__ == "__main__":
    main()
