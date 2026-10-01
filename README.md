# 📡 Signal Desk — Live Trading Signals

> Live forex, crypto and stock signals with clear **BUY / SELL** calls.

**▶️ [Open the live app](https://darthsandd.github.io/signal-desk/)**

An installable web app (PWA) that surfaces market signals in plain language — no chart archaeology, no indicator soup. You get a direction, not a homework assignment.

---

## What it does

- **Live signals** across forex, crypto, and stocks
- Clear **BUY / SELL** calls — decision-first, not indicator-first
- **Installable as an app** — add to home screen, runs fullscreen standalone
- **Dark-first UI** built for long sessions
- Works on desktop and mobile from the same URL

## Why a PWA

No app store, no install friction, no update lag. You get native-app behavior (home-screen icon, standalone window, offline shell) from a single URL that's always current.

---

## Tech

`HTML` · `CSS` · `JavaScript` · Web App Manifest

```
index.html              # the app
manifest.webmanifest    # PWA install config
gate.js                 # access gate
data.json               # signal data
icon-192.png            # app icons
icon-512.png
icon.svg
```

---

## Run locally

```bash
git clone https://github.com/DarthSandD/signal-desk.git
cd signal-desk
python -m http.server 8080
# → http://localhost:8080
```

---

## ⚠️ Not financial advice

This tool surfaces signals. It does not know your risk tolerance, your position size, or your goals. **Always do your own research.** Markets carry real risk of loss.

---

## License

Open source. See repository for details.

**Built by [Darren Lieu](https://darrenlin.pages.dev/)** · [@DarthSandD](https://github.com/DarthSandD)
