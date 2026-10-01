#!/usr/bin/env python3
"""
Signal Desk — refresh + publish.
1. Recompute signals (signals.py) → data.json + baked fallback in index.html
2. Commit + push to GitHub → GitHub Pages rebuilds automatically
3. Print a Telegram-ready alert with the best signal

Run: python publish.py
Exit 0 on success, 1 on failure (cron surfaces a non-zero exit).
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE_URL = "https://darthsandd.github.io/signal-desk/"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, **kw)


def main():
    # 1) Recompute signals
    r = run([sys.executable, "signals.py"])
    if r.returncode != 0:
        print(f"[ERROR] signals.py failed:\n{r.stderr}", file=sys.stderr)
        return 1

    data = json.loads((HERE / "data.json").read_text(encoding="utf-8"))
    best = data.get("best")
    counts = data.get("counts", {})

    # 2) Commit + push (Pages rebuilds on push)
    run(["git", "add", "-A"])
    diff = run(["git", "diff", "--cached", "--quiet"])
    pushed = False
    if diff.returncode != 0:  # there are staged changes
        ts = data["generated"][:16].replace("T", " ")
        run(["git", "commit", "-m", f"data: refresh signals {ts}Z"])
        p = run(["git", "push", "origin", "HEAD"])
        pushed = p.returncode == 0
        if not pushed:
            print(f"[WARN] push failed: {p.stderr}", file=sys.stderr)

    # 3) Telegram alert
    if best:
        up = "BUY" in best["signal"]
        icon = "🟢" if up else ("🔴" if "SELL" in best["signal"] else "⚪")
        print(
            f"{icon} *Signal Desk — {best['signal']}* — {best['symbol']}\n"
            f"• Price: `{best['priceText']}`  ({best['change']:+.2f}%)\n"
            f"• Confidence: `{best['confidence']}%`  ·  RSI `{best['rsi']}`\n"
            f"• Entry `{best['entry']}`  ·  Stop `{best['stop']}`  ·  Target `{best['target']}`\n"
            f"• {counts.get('forex',0)} forex · {counts.get('crypto',0)} crypto · "
            f"{counts.get('stocks',0)} stocks scanned\n"
            f"🔗 {SITE_URL}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
