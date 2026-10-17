"""
The tracked universe — heavyweights of Nifty 50, Nifty Bank and Nifty Financial
Services, with index weights from the NSE factsheets dated 30 Sep 2026
(D:\\ApexOptions\\ind_*.pdf).

Weight tags:  exact    = printed in the factsheet's top-10 table
              estimate = not in that table (factsheets list only the top 10);
                         carried from the May-2026 Indexogram derivation used by
                         MYTHOS. Edit here when NSE publishes new weights.
A 0 weight means "not a constituent" (or unknown and deliberately excluded
from that index's weighted sums).
"""

# symbol: (nifty50_w, banknifty_w, finnifty_w, nifty_tag, group)
STOCKS = {
    "HDFCBANK":   (10.38, 18.61, 18.63, "exact",    "bank"),
    "ICICIBANK":  (9.05,  14.18, 14.20, "exact",    "bank"),
    "RELIANCE":   (7.58,  0.0,   0.0,   "exact",    "energy"),
    "BHARTIARTL": (5.10,  0.0,   0.0,   "exact",    "telecom"),
    "LT":         (4.20,  0.0,   0.0,   "exact",    "infra"),
    "SBIN":       (3.79,  9.93,  9.94,  "exact",    "bank"),
    "AXISBANK":   (3.37,  10.06, 10.18, "exact",    "bank"),
    "INFY":       (3.35,  0.0,   0.0,   "exact",    "it"),
    "KOTAKBANK":  (2.93,  10.20, 10.11, "exact",    "bank"),
    "M&M":        (2.52,  0.0,   0.0,   "exact",    "auto"),
    "TCS":        (2.70,  0.0,   0.0,   "estimate", "it"),
    "ITC":        (2.56,  0.0,   0.0,   "estimate", "fmcg"),
    "BAJFINANCE": (2.20,  0.0,   8.62,  "estimate", "nbfc"),
    "HINDUNILVR": (1.85,  0.0,   0.0,   "estimate", "fmcg"),
    "FEDERALBNK": (0.0,   6.56,  0.0,   "n/a",      "bank"),
    "INDUSINDBK": (0.0,   4.97,  0.0,   "n/a",      "bank"),
    "AUBANK":     (0.0,   4.85,  0.0,   "n/a",      "bank"),
    "IDFCFIRSTB": (0.0,   4.54,  0.0,   "n/a",      "bank"),
    "BANKBARODA": (0.0,   3.59,  0.0,   "n/a",      "bank"),
    "SHRIRAMFIN": (0.0,   0.0,   4.53,  "n/a",      "nbfc"),
    "BSE":        (0.0,   0.0,   4.16,  "n/a",      "nbfc"),
    "BAJAJFINSV": (0.0,   0.0,   3.31,  "n/a",      "nbfc"),
    "SBILIFE":    (0.0,   0.0,   2.51,  "n/a",      "insurance"),
}

# Known Breeze ISEC codes (from MYTHOS's resolved cache, 16 Oct 2026). Others are
# resolved at startup with breeze.get_names() and cached in data/token_cache.json.
ISEC_HINT = {
    "HDFCBANK": "HDFBAN", "ICICIBANK": "ICIBAN", "RELIANCE": "RELIND",
    "BHARTIARTL": "BHAAIR", "LT": "LARTOU", "INFY": "INFTEC", "SBIN": "STABAN",
    "AXISBANK": "AXIBAN", "KOTAKBANK": "KOTMAH", "ITC": "ITC", "TCS": "TCS",
    "M&M": "MAHMAH", "BAJFINANCE": "BAJFI", "HINDUNILVR": "HINLEV",
}

# Index codes tried in order (first that resolves wins; result cached).
INDEX_CODES = {
    "NIFTY": ["NIFTY"],
    "BANKNIFTY": ["CNXBAN", "BANKNIFTY", "NIFBAN"],
    "FINNIFTY": ["NIFFIN", "FINNIFTY", "NIFSER"],
}

NIFTY_TRACKED_WEIGHT = sum(v[0] for v in STOCKS.values())


def nifty_weight(sym: str) -> float:
    return STOCKS.get(sym, (0.0,))[0]
