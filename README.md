# Bloomberg Terminal (Mini)

A single-page Bloomberg-style trading terminal. Real-time markets, intraday
charts, a customizable Workspace dashboard, an AI analyst, and macro/portfolio
research tools — all driven by Yahoo Finance, FRED, Groq, and Anthropic.

**Live site:** https://bloomberg-terminal-vi23.onrender.com

## Stack at a glance

- **Backend**: FastAPI + uvicorn (`server.py`) — REST endpoints + a WebSocket price stream
- **Frontend**: one big `index.html` (vanilla JS, Chart.js, candlesticks via `chartjs-chart-financial`)
- **Data**: `yfinance` (Yahoo) for prices/fundamentals, `requests` to BLS/FRED/SEC for macro
- **AI**: Groq (Llama 3.3) for chat, Anthropic (Claude) for the morning brief
- **Hosting**: Render (Blueprint, see `render.yaml`)

## ⚠️ Two apps in one repo — don't confuse them

| File | What it is | Status |
| --- | --- | --- |
| **`server.py` + `index.html`** | The deployed site. | This is what you change. |
| `app.py` | A separate local Streamlit research tool. | Not deployed. Ignore unless you need it. |

If you're "fixing the site," you're working in `server.py` + `index.html`. Always.

## Where things are

- `server.py` — every backend endpoint. New routes go at the bottom.
- `index.html` — the entire frontend. Single page, multiple `<div class="page">` panels switched via the nav.
- `valuation.py` — the Value Screener's math (5 valuation methods). Imported by `server.py`.
- `data/` — standalone Streamlit dashboards (legacy / dev tools). Not part of the deployed site.
- `render.yaml` — Render deploy config.
- `.env` — local secrets (gitignored). Render reads its own env vars from the dashboard.

## Documentation

- **[HANDOFF.md](HANDOFF.md)** — for the boss / the company taking ownership. Hosting, API keys, ops playbook.
- **[CLAUDE.md](CLAUDE.md)** — for whoever (or whatever AI) edits the code next. Architecture, conventions, gotchas, "how do I add X" recipes.

## Local dev

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8077
# open http://localhost:8077
```

You need a `.env` with `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, and (optionally) `FRED_API_KEY` for the live calendar numbers.

## Deploy

`git push origin main` → Render auto-deploys in ~3–5 min. That's the whole loop.
See HANDOFF.md for the dashboard walkthrough.
