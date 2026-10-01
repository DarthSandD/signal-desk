#!/usr/bin/env python3
"""
Signal Desk — data + signal engine (v3)
Multi-timeframe: computes signals on DAILY (D1) bars plus a WEEKLY (W1) higher-
timeframe bias, with a TRUE ATR (Wilder, from high/low/close) and ATR% so the
browser can re-anchor entry/stop/target to the LIVE price instead of a stale close.

Writes data.json (and bakes a fallback into index.html).
Run: python signals.py
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

HERE = Path(__file__).resolve().parent
DATA_JSON = HERE / "data.json"
INDEX_HTML = HERE / "index.html"

YF = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Timeframes: (code, yahoo interval, yahoo range, human description, horizon)
TF_PRIMARY = ("D1", "1d", "6mo", "Daily swing", "days–weeks")
TF_HIGHER = ("W1", "1wk", "2y", "Weekly bias", "weeks–months")

# Risk model (documented in the UI)
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 2.25   # = 1.5R

FOREX = [
    ("EURUSD=X", "EUR/USD", "Euro / US Dollar"),
    ("USDJPY=X", "USD/JPY", "US Dollar / Japanese Yen"),
    ("GBPUSD=X", "GBP/USD", "British Pound / US Dollar"),
    ("AUDUSD=X", "AUD/USD", "Australian Dollar / US Dollar"),
    ("USDCAD=X", "USD/CAD", "US Dollar / Canadian Dollar"),
    ("USDCHF=X", "USD/CHF", "US Dollar / Swiss Franc"),
    ("NZDUSD=X", "NZD/USD", "New Zealand Dollar / US Dollar"),
    ("EURJPY=X", "EUR/JPY", "Euro / Japanese Yen"),
    ("GBPJPY=X", "GBP/JPY", "British Pound / Japanese Yen"),
    ("GC=F", "XAU/USD", "Gold / US Dollar"),
]
CRYPTO = [
    ("BTC-USD", "BTC", "Bitcoin"), ("ETH-USD", "ETH", "Ethereum"),
    ("SOL-USD", "SOL", "Solana"), ("XRP-USD", "XRP", "XRP"),
    ("BNB-USD", "BNB", "BNB"), ("ADA-USD", "ADA", "Cardano"),
    ("DOGE-USD", "DOGE", "Dogecoin"), ("AVAX-USD", "AVAX", "Avalanche"),
]
STOCKS = [
    ("AAPL", "AAPL", "Apple"), ("MSFT", "MSFT", "Microsoft"),
    ("NVDA", "NVDA", "NVIDIA"), ("TSLA", "TSLA", "Tesla"),
    ("GOOGL", "GOOGL", "Alphabet"), ("AMZN", "AMZN", "Amazon"),
    ("META", "META", "Meta"), ("AMD", "AMD", "AMD"),
    ("SPY", "SPY", "S&P 500 ETF"), ("^GSPC", "S&P 500", "S&P 500 Index"),
]
ICON = {"forex": "💱", "crypto": "🪙", "stocks": "📈"}


# ── Indicators ──────────────────────────────────────────────────────────
def sma(x, n):
    return sum(x[-n:]) / n if len(x) >= n else None


def ema_series(x, n):
    if not x:
        return []
    k = 2 / (n + 1)
    out = [x[0]]
    for v in x[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(x, n=14):
    if len(x) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(x)):
        d = x[i] - x[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains[-n:]) / n, sum(losses[-n:]) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def macd_hist(x):
    if len(x) < 35:
        return None
    m = [a - b for a, b in zip(ema_series(x, 12), ema_series(x, 26))]
    s = ema_series(m, 9)
    return m[-1] - s[-1]


def true_atr(highs, lows, closes, n=14):
    """True Average True Range (Wilder) from OHLC — the real thing, not a close proxy."""
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        if h is None or l is None or pc is None:
            continue
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return None
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def score_bars(bars, period_word="periods"):
    """bars = {'close':[], 'high':[], 'low':[]} → signal dict (timeframe-agnostic)."""
    x = bars["close"]
    if len(x) < 30:
        return None
    price = x[-1]
    s20, s50 = sma(x, 20), sma(x, 50)
    r = rsi(x)
    h = macd_hist(x)
    a = true_atr(bars["high"], bars["low"], x)
    score = 0.0
    reasons = []

    if s20 and s50:
        if price > s20 > s50:
            score += 2.0
            reasons.append("Price above rising 20/50 MA")
        elif price < s20 < s50:
            score -= 2.0
            reasons.append("Price below falling 20/50 MA")
        elif price > s20:
            score += 0.5
            reasons.append("Above 20-period MA")
        else:
            score -= 0.5
            reasons.append("Below 20-period MA")

    if r is not None:
        if r < 30:
            score += 1.0
            reasons.append(f"Oversold (RSI {r:.0f})")
        elif r > 70:
            score -= 1.0
            reasons.append(f"Overbought (RSI {r:.0f})")
        else:
            reasons.append(f"RSI {r:.0f} — neutral")

    if h is not None:
        score += 0.75 if h > 0 else -0.75
        reasons.append("MACD bullish" if h > 0 else "MACD bearish")

    if len(x) > 21:
        mom = (price - x[-21]) / x[-21] * 100
        if mom > 1:
            score += 0.5
            reasons.append(f"+{mom:.1f}% over 20 {period_word}")
        elif mom < -1:
            score -= 0.5
            reasons.append(f"{mom:.1f}% over 20 {period_word}")

    if score >= 2.5:
        sig = "STRONG BUY"
    elif score >= 1.0:
        sig = "BUY"
    elif score <= -2.5:
        sig = "STRONG SELL"
    elif score <= -1.0:
        sig = "SELL"
    else:
        sig = "NEUTRAL"

    atr_pct = (a / price) if (a and price) else None
    return {
        "signal": sig,
        "score": round(score, 2),
        "confidence": max(35, min(95, round(50 + abs(score) * 11))),
        "rsi": round(r, 1) if r is not None else None,
        "sma20": round(s20, 6) if s20 else None,
        "sma50": round(s50, 6) if s50 else None,
        "macd": round(h, 6) if h is not None else None,
        "atr": round(a, 6) if a else None,
        "atrPct": round(atr_pct, 6) if atr_pct else None,
        "reasons": reasons[:4],
    }


# ── Fetch ───────────────────────────────────────────────────────────────
def yf_bars(sym, interval, rng):
    r = requests.get(YF.format(sym), params={"interval": interval, "range": rng},
                     headers=UA, timeout=20)
    r.raise_for_status()
    d = r.json()["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    ts = d.get("timestamp", [])
    closes, highs, lows, times = [], [], [], []
    for i, c in enumerate(q["close"]):
        if c is None:
            continue
        closes.append(c)
        highs.append(q["high"][i] if q["high"][i] is not None else c)
        lows.append(q["low"][i] if q["low"][i] is not None else c)
        times.append(ts[i] if i < len(ts) else 0)
    return {"close": closes, "high": highs, "low": lows, "time": times}


def fmt_price(p):
    if p is None:
        return "—"
    a = abs(p)
    if a >= 1000:
        return f"{p:,.2f}"
    if a >= 10:
        return f"{p:,.2f}"
    if a >= 1:
        return f"{p:.4f}"
    return f"{p:.5f}"


def build_entry(sym, disp, name, market, primary, higher):
    sig = score_bars(primary, "days")
    if not sig:
        return None
    x = primary["close"]
    price = x[-1]
    prev = x[-2] if len(x) > 1 else price
    change = ((price - prev) / prev * 100) if prev else 0.0

    hi = score_bars(higher, "weeks") if higher and len(higher["close"]) >= 30 else None
    mtf = None
    if hi:
        p_dir = 1 if "BUY" in sig["signal"] else (-1 if "SELL" in sig["signal"] else 0)
        h_dir = 1 if "BUY" in hi["signal"] else (-1 if "SELL" in hi["signal"] else 0)
        mtf = {
            "tf": TF_HIGHER[0],
            "signal": hi["signal"],
            "rsi": hi["rsi"],
            "aligned": bool(p_dir and h_dir and p_dir == h_dir),
        }

    return {
        "symbol": disp, "ticker": sym, "name": name,
        "market": market.capitalize(), "marketKey": market, "icon": ICON[market],
        "price": round(price, 6), "priceText": fmt_price(price),
        "change": round(change, 2),
        "timeframe": TF_PRIMARY[0],
        "timeframeDesc": TF_PRIMARY[3],
        "timeframeHorizon": TF_PRIMARY[4],
        "history": [round(v, 6) for v in x[-90:]],
        "spark": [round(v, 6) for v in x[-30:]],
        "bars": len(x),
        "asOf": (primary["time"][-1] if primary.get("time") else None),
        "mtf": mtf,
        **sig,
    }


def collect(group, market):
    out = []
    for sym, disp, name in group:
        try:
            p = yf_bars(sym, TF_PRIMARY[1], TF_PRIMARY[2])
            if len(p["close"]) < 30:
                raise ValueError(f"only {len(p['close'])} bars")
            try:
                h = yf_bars(sym, TF_HIGHER[1], TF_HIGHER[2])
            except Exception:
                h = None
            e = build_entry(sym, disp, name, market, p, h)
            if e:
                out.append(e)
        except Exception as ex:
            print(f"[WARN] {disp} ({sym}): {ex}", file=sys.stderr)
    return out


def detect_session():
    h = datetime.now(timezone.utc).hour
    if 0 <= h < 7:
        return "Sydney Session", "🌏", "Low volume · Aussie pairs active"
    if 7 <= h < 16:
        return "Tokyo / Asian Session", "🌏", "Asian volatility · USD/JPY focus"
    if 16 <= h < 21:
        return "London Session", "🌍", "Highest liquidity · EUR/GBP candles"
    return "New York Session", "🌎", "US-driven · highest volume window"


def main():
    session, icon, meta = detect_session()
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "session": {"name": session, "icon": icon, "meta": meta},
        "timeframes": {
            "primary": {"code": TF_PRIMARY[0], "desc": TF_PRIMARY[3],
                        "horizon": TF_PRIMARY[4], "interval": TF_PRIMARY[1],
                        "range": TF_PRIMARY[2]},
            "higher": {"code": TF_HIGHER[0], "desc": TF_HIGHER[3],
                       "horizon": TF_HIGHER[4], "interval": TF_HIGHER[1],
                       "range": TF_HIGHER[2]},
        },
        "risk": {"stopMult": ATR_STOP_MULT, "targetMult": ATR_TARGET_MULT, "rr": 1.5},
        "markets": {
            "forex": collect(FOREX, "forex"),
            "crypto": collect(CRYPTO, "crypto"),
            "stocks": collect(STOCKS, "stocks"),
        },
    }

    allsym = data["markets"]["forex"] + data["markets"]["crypto"] + data["markets"]["stocks"]

    def rank(e):
        align = 0.5 if (e.get("mtf") and e["mtf"]["aligned"]) else 0
        return (abs(e["score"]) + align, e["confidence"])

    ranked = sorted(allsym, key=rank, reverse=True)
    data["best"] = ranked[0] if ranked else None
    data["counts"] = {k: len(v) for k, v in data["markets"].items()}
    data["aligned"] = sum(1 for e in allsym if e.get("mtf") and e["mtf"]["aligned"])

    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {sum(data['counts'].values())} symbols on {TF_PRIMARY[0]} "
          f"(forex {data['counts']['forex']}, crypto {data['counts']['crypto']}, "
          f"stocks {data['counts']['stocks']}) · {data['aligned']} aligned with {TF_HIGHER[0]}",
          file=sys.stderr)
    if data["best"]:
        b = data["best"]
        ap = f"{b['atrPct']*100:.2f}%" if b["atrPct"] else "n/a"
        print(f"[BEST] {b['symbol']} → {b['signal']} (score {b['score']}, "
              f"conf {b['confidence']}%, ATR {ap})", file=sys.stderr)

    if INDEX_HTML.exists():
        html = INDEX_HTML.read_text(encoding="utf-8")
        payload = json.dumps(data, ensure_ascii=False)
        new, n = re.subn(r'(<script id="bakedData"[^>]*>).*?(</script>)',
                         lambda m: m.group(1) + payload + m.group(2),
                         html, flags=re.DOTALL)
        if n:
            INDEX_HTML.write_text(new, encoding="utf-8")
            print("[OK] baked fallback into index.html", file=sys.stderr)
        else:
            print("[WARN] bakedData tag not found in index.html", file=sys.stderr)


if __name__ == "__main__":
    main()
