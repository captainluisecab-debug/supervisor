"""
kraken_account_monitor.py — D-063 enzobot-INDEPENDENT live Kraken account + BTC regime source.
Drop-in for supervisor_governor._read_enzobot_state(). READ-ONLY against the exchange.

  - BTC regime: zerobot's public data_kraken.fetch_ohlc -> EMA(fast/slow) trend + ATR/price expected_move
                -> enzobot classify_regime thresholds (COPIED here; NO dependency on the archived enzobot pkg).
  - Live equity: zerobot's proven KrakenCcxtBroker.get_total_balances() + ticker (read-only).

Anchor (2026-06-24 enzobot live feedback): BTC regime "DOWN", equity $3,408.61, vol_gate 0.003.
Regime path validated offline against that anchor (MATCH). Equity path validated during the Phase-A bake.
"""
import os, json, sys

ZEROBOT_DIR = r"C:/Projects/zerobot"
_STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kraken_account_monitor_state.json")
PAIR = "BTC/USD"
VOL_GATE = 0.003                          # enzobot effective VOLATILITY_ENTRY_GATE / ATR_FLOOR_PCT
FAST_MA, SLOW_MA, TF_MIN = 10, 30, 240    # enzobot BTC 4H market-regime params (validate/tune at bake)

def _ema(vals, n):
    if not vals: return 0.0
    k = 2.0/(n+1.0); e = vals[0]
    for v in vals[1:]: e = v*k + e*(1.0-k)
    return e

def _atr(candles, n=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i].h, candles[i].l, candles[i-1].c
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    seg = trs[-n:] if len(trs) >= n else trs
    return sum(seg)/len(seg) if seg else 0.0

def _classify_regime(trend_up, expected_move):
    # thresholds verbatim from enzobot/strategy_one.classify_regime
    vg = VOL_GATE
    if trend_up and expected_move >= vg: return "UP"
    if (not trend_up) and expected_move >= vg: return "DOWN"
    if expected_move < vg*0.75: return "QUIET"
    return "NEUTRAL"

def get_btc_regime():
    if ZEROBOT_DIR not in sys.path: sys.path.insert(0, ZEROBOT_DIR)
    from data_kraken import fetch_ohlc
    candles = fetch_ohlc(PAIR, TF_MIN, max(SLOW_MA+25, 60))
    closes = [c.c for c in candles]
    fast = _ema(closes, FAST_MA); slow = _ema(closes, SLOW_MA)
    price = closes[-1]; atr = _atr(candles, 14)
    em = atr/max(1e-9, price); trend_up = fast >= slow
    return _classify_regime(trend_up, em), {"price": round(price), "fast": round(fast), "slow": round(slow),
                                            "expected_move": round(em, 4), "trend_up": trend_up}

def get_live_equity():
    """Reuse zerobot's proven live Kraken read (READ-ONLY: balances + ticker). Returns (equity, usd, btc)."""
    if ZEROBOT_DIR not in sys.path: sys.path.insert(0, ZEROBOT_DIR)
    from broker import KrakenCcxtBroker
    from settings import load_settings   # zerobot's canonical creds loader (engine.py:535 pattern)
    cfg = load_settings()
    br = KrakenCcxtBroker(cfg.kraken_key, cfg.kraken_secret)
    tot = br.get_total_balances()
    usd = float(tot.get("ZUSD", tot.get("USD", 0.0)) or 0.0)
    btc = float(tot.get("XXBT", tot.get("XBT", tot.get("BTC", 0.0))) or 0.0)
    mid = br.get_mid_price(PAIR) if btc > 1e-8 else 0.0
    dust = 0.0
    for a in ("NEAR", "POL", "XRP", "ETH"):
        amt = float(tot.get(a, 0.0) or 0.0)
        if amt > 0:
            try: dust += amt * br.get_mid_price(a + "/USD")
            except Exception: pass
    return usd + btc*mid + dust, usd, btc

def _load():
    try: return json.load(open(_STATE))
    except Exception: return {}
def _save(d):
    try: json.dump(d, open(_STATE, "w"))
    except Exception: pass

def read_kraken_account():
    """Drop-in for supervisor_governor._read_enzobot_state(): identical dict shape."""
    try: regime, _dbg = get_btc_regime()
    except Exception: regime = "NEUTRAL"
    equity = cash = btc = None
    try: equity, cash, btc = get_live_equity()
    except Exception: pass
    st = _load()
    if equity:
        peak = max(st.get("equity_peak", equity), equity)
        st.update(equity_peak=peak, equity=equity); _save(st)
        dd = (equity/peak - 1)*100 if peak else 0.0
    else:
        equity = st.get("equity", 0.0); peak = st.get("equity_peak", equity); dd = 0.0; cash = equity
    return {
        "sleeve": "kraken",
        "equity": equity, "dd_pct": dd, "cash": cash if cash is not None else equity,
        "open_positions": 1 if (btc and btc > 1e-6) else 0,
        "portfolio": {"equity": equity, "dd_pct": dd, "cash": cash, "open_positions": 0},
        "pair_regime": {PAIR: regime},
        "pair_scores": {PAIR: 75.0},
        "mode": "MONITOR",
    }

if __name__ == "__main__":
    r, dbg = get_btc_regime()
    print("BTC regime:", r, "| debug:", dbg)
