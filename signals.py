#!/usr/bin/env python3
"""
Signal Desk — data + signal engine (v2)
Fetches live prices + history for Forex / Crypto / Stocks, computes a
BUY/SELL signal per symbol, picks the single best opportunity, and writes
data.json (plus bakes a fallback copy into index.html).

Sources: Yahoo Finance (all), Frankfurter (forex fallback), CoinGecko (crypto fallback).
Run: python signals.py
"""

import json
import re
import sys
from datetime import datetime, timezone, timedelta
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
FRANKFURTER_HIST = "https://api.frankfurter.dev/v1/{start}..{end}"
COINGECKO_CHART = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ── Symbol universe ─────────────────────────────────────────────────────
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
    ("BTC-USD", "BTC", "Bitcoin"),
    ("ETH-USD", "ETH", "Ethereum"),
    ("SOL-USD", "SOL", "Solana"),
    ("XRP-USD", "XRP", "XRP"),
    ("BNB-USD", "BNB", "BNB"),
    ("ADA-USD", "ADA", "Cardano"),
    ("DOGE-USD", "DOGE", "Dogecoin"),
    ("AVAX-USD", "AVAX", "Avalanche"),
]
STOCKS = [
    ("AAPL", "AAPL", "Apple"),
    ("MSFT", "MSFT", "Microsoft"),
    ("NVDA", "NVDA", "NVIDIA"),
    ("TSLA", "TSLA", "Tesla"),
    ("GOOGL", "GOOGL", "Alphabet"),
    ("AMZN", "AMZN", "Amazon"),
    ("META", "META", "Meta"),
    ("AMD", "AMD", "AMD"),
    ("SPY", "SPY", "S&P 500 ETF"),
    ("^GSPC", "S&P 500", "S&P 500 Index"),
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


def atr(x, n=14):
    """Average true range proxy from closes (no OHLC needed for a stop distance)."""
    if len(x) < n + 1:
        return None
    trs = [abs(x[i] - x[i - 1]) for i in range(1, len(x))]
    return sum(trs[-n:]) / n


def compute_signal(x):
    """Score-based signal: trend + RSI + MACD + momentum. Returns a dict."""
    if len(x) < 30:
        return None
    price = x[-1]
    s20, s50 = sma(x, 20), sma(x, 50)
    r = rsi(x)
    h = macd_hist(x)
    a = atr(x)
    score = 0.0
    reasons = []

    if s20 and s50:
        if price > s20 > s50:
            score += 2.0
            reasons.append("Uptrend: price above rising 20/50 MA")
        elif price < s20 < s50:
            score -= 2.0
            reasons.append("Downtrend: price below falling 20/50 MA")
        elif price > s20:
            score += 0.5
            reasons.append("Above 20-day average")
        else:
            score -= 0.5
            reasons.append("Below 20-day average")

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
            reasons.append(f"+{mom:.1f}% over 20 days")
        elif mom < -1:
            score -= 0.5
            reasons.append(f"{mom:.1f}% over 20 days")

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

    conf = max(35, min(95, round(50 + abs(score) * 11)))

    # Trade levels from ATR (risk-managed 1.5R target)
    entry = price
    if a and a > 0:
        if score >= 1.0:
            stop, target = price - 1.5 * a, price + 2.25 * a
        elif score <= -1.0:
            stop, target = price + 1.5 * a, price - 2.25 * a
        else:
            stop = target = None
    else:
        stop = target = None

    return {
        "signal": sig,
        "score": round(score, 2),
        "confidence": conf,
        "rsi": round(r, 1) if r is not None else None,
        "sma20": round(s20, 6) if s20 else None,
        "sma50": round(s50, 6) if s50 else None,
        "macd": round(h, 6) if h is not None else None,
        "atr": round(a, 6) if a else None,
        "entry": round(entry, 6),
        "stop": round(stop, 6) if stop else None,
        "target": round(target, 6) if target else None,
        "reasons": reasons[:4],
    }


# ── Fetchers ────────────────────────────────────────────────────────────
def yf_history(sym, rng="6mo"):
    r = requests.get(YF.format(sym), params={"interval": "1d", "range": rng},
                     headers=UA, timeout=20)
    r.raise_for_status()
    d = r.json()["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    ts = d.get("timestamp", [])
    closes = [(t, c) for t, c in zip(ts, q["close"]) if c is not None]
    return [c for _, c in closes]


def frankfurter_history(base="EUR"):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=200)
    r = requests.get(FRANKFURTER_HIST.format(start=start, end=end),
                     params={"from": base, "to": "USD"}, headers=UA, timeout=20)
    r.raise_for_status()
    return sorted(r.json()["rates"].items())


def coingecko_history(cid):
    r = requests.get(COINGECKO_CHART.format(id=cid),
                     params={"vs_currency": "usd", "days": 180},
                     headers=UA, timeout=20)
    r.raise_for_status()
    return [p[1] for p in r.json().get("prices", [])]


def fmt_price(p):
    if p is None:
        return "—"
    ap = abs(p)
    if ap >= 1000:
        return f"{p:,.2f}"
    if ap >= 10:
        return f"{p:,.2f}"
    if ap >= 1:
        return f"{p:.4f}"
    return f"{p:.5f}"


def build_entry(sym, disp, name, market, x):
    sig = compute_signal(x)
    if not sig:
        return None
    price = x[-1]
    prev = x[-2] if len(x) > 1 else price
    change = ((price - prev) / prev * 100) if prev else 0.0
    hist = x[-90:]
    return {
        "symbol": disp,
        "ticker": sym,
        "name": name,
        "market": market.capitalize(),
        "marketKey": market,
        "icon": ICON[market],
        "price": round(price, 6),
        "priceText": fmt_price(price),
        "change": round(change, 2),
        "history": [round(v, 6) for v in hist],
        "spark": [round(v, 6) for v in x[-30:]],
        **sig,
    }


def detect_session():
    h = datetime.now(timezone.utc).hour
    if 0 <= h < 7:
        return "Sydney Session", "🌏", "Low volume · Aussie pairs active"
    if 7 <= h < 16:
        return "Tokyo / Asian Session", "🌏", "Asian volatility · USD/JPY focus"
    if 16 <= h < 21:
        return "London Session", "🌍", "Highest liquidity · EUR/GBP candles"
    return "New York Session", "🌎", "US-driven · highest volume window"


def collect(group, market):
    out = []
    for sym, disp, name in group:
        try:
            x = yf_history(sym)
            if len(x) < 30:
                raise ValueError(f"only {len(x)} points")
            e = build_entry(sym, disp, name, market, x)
            if e:
                out.append(e)
        except Exception as ex:
            print(f"[WARN] {disp} ({sym}): {ex}", file=sys.stderr)
    return out


def main():
    session, icon, meta = detect_session()
    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "session": {"name": session, "icon": icon, "meta": meta},
        "markets": {
            "forex": collect(FOREX, "forex"),
            "crypto": collect(CRYPTO, "crypto"),
            "stocks": collect(STOCKS, "stocks"),
        },
    }

    allsym = data["markets"]["forex"] + data["markets"]["crypto"] + data["markets"]["stocks"]
    ranked = sorted(allsym, key=lambda e: (abs(e["score"]), e["confidence"]), reverse=True)
    data["best"] = ranked[0] if ranked else None
    data["counts"] = {k: len(v) for k, v in data["markets"].items()}

    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {sum(data['counts'].values())} symbols "
          f"(forex {data['counts']['forex']}, crypto {data['counts']['crypto']}, "
          f"stocks {data['counts']['stocks']})", file=sys.stderr)
    if data["best"]:
        b = data["best"]
        print(f"[BEST] {b['symbol']} → {b['signal']} (score {b['score']}, conf {b['confidence']}%)",
              file=sys.stderr)

    # Bake a fallback copy into index.html so the page renders offline
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
