# CLAUDE.md — orientation for the next developer

A condensed map of how this codebase actually works, the conventions to follow,
and the bugs we've already hit so you don't hit them again. Written so a fresh
Claude Code session — or a human dev — can pick up and ship without re-discovering
the wheel.

---

## Architecture in one paragraph

`server.py` is a FastAPI app serving REST endpoints + one WebSocket (`/ws/prices`).
It returns JSON for everything except `/` (which serves `index.html`).
`index.html` is a single-page app: one HTML file, one big `<script>` block, multiple
`<div class="page">` panels switched via two functions — `showPage(name)` for the
top-level tabs (Brief, Markets, News, AI Chat) and `navTo(name, groupId)` for the
dropdown submenu items. State (current symbol, watchlist, portfolio, alerts, layout)
lives in `localStorage` — there's no login, no user accounts, no backend DB.

The **Workspace** page is a customizable dashboard that loads other pages inside
`<iframe>` tiles. Each iframe loads the same `index.html` with `?ws=<pageId>` so
it knows to hide the chrome and route to that page. See "Workspace" section below.

---

## Two-app trap (READ THIS)

The repo contains **two completely separate Python apps**:

- `server.py` (FastAPI) — **the deployed site**
- `app.py` (Streamlit) — a separate local research tool, **not** deployed

When you're told "fix the site" or "add to the site," you always mean `server.py`
and `index.html`. `app.py` is a sibling project that lives in the same repo for
historical reasons. Same for the `data/` folder — those are standalone Streamlit
dashboards used during development, not part of the live site.

If you find yourself editing `app.py` after a "fix the site" request, stop.

---

## Conventions to follow

### Backend (`server.py`)

**Caching pattern** — every endpoint that hits Yahoo or another rate-limited API
must cache. Use the existing helpers:

```python
data, hit = cached(key, ttl=60)
if hit: return data
# ... do the work ...
set_cache(key, result)
return result
```

TTLs in use:
- Live prices / quotes: **30–60 seconds**
- Historical data: **60 seconds**
- News / sector / heatmap: **5–10 minutes**
- Calendar / morning brief: **30 minutes**

**Parallelization** — when an endpoint fans out to many tickers, never loop
serially. Use `_parallel(fn, items, workers=16)`:

```python
def _one(sym):
    try:
        info = yf.Ticker(sym).info
        return {"symbol": sym, "price": info.get("currentPrice")}
    except Exception:
        return None  # _parallel's worker MUST swallow its own errors
results = [r for r in _parallel(_one, symbols) if r]
```

We have hit "endpoint takes 70 seconds" multiple times. The fix is always
caching + parallelization. The serial pattern is a footgun.

**NaN values break JSON.** Pandas `NaN` cannot be JSON-encoded — it produces a
silent 500 at response time, *after* your try/except. Always sanitize before
returning:

```python
def _clean(series):
    return [None if pd.isna(v) else float(v) for v in series]
```

Chart.js renders `null` as a gap. This bit us hard in `/compare` with DVN data.

**Yahoo rate limits** are real. We install a resilient impersonating session at
module load (see top of `server.py`); leave it alone. The global exception handler
catches `YFRateLimitError` and returns 503 with a clear message.

### Frontend (`index.html`)

**One file, no build step.** Refresh the browser to see changes — no bundler,
no transpilation, no node. This is by design; keep it that way unless someone
demands TypeScript.

**Pages are `<div class="page" id="page-X">`.** Hidden by default, shown by
adding the `.active` class. Switching is done in `navTo()` and `showPage()`.

**Adding a new page** — follow this exact recipe:

1. Add `<div class="page" id="page-X">…</div>` inside `<div id="main">`
2. Add a nav item: `<div class="nav-dropdown-item" onclick="navTo('X','grp-<group>')">…</div>`
3. Add a one-line load hook inside `navTo()`: `if(name==="X") loadX();`
4. (Workspace) Add `{id:"X", name:"…"}` to `WS_PAGES` (under the matching group)
5. (Workspace) Add `X:"grp-<group>"` to the iframe-mode `groupMap`

**Chart.js conventions** — destroy the previous chart instance before creating
a new one (`if (myChart) myChart.destroy();`). Reuse `chartOpts` where possible.
For zoom, use `_stdZoomConfig()` and `_attachResetOnDblClick()` — they handle
wheel/drag/pinch/double-click consistently.

**State in localStorage:**
- `watchlist` — user's tickers
- `portfolio` — positions, **uses field name `avgCost` not `cost`**
- `alerts` — price alerts
- `workspace_layout_v1` — current Workspace layout (autosaved on every change)
- `workspace_user_presets_v1` — user-named preset layouts

---

## The Workspace (most complex feature)

A drag/resize dashboard where each tile is an `<iframe>` of one of the site's
pages. Each iframe loads `index.html?ws=<pageId>&sym=<ticker>&syms=<list>&v=<ver>`.
The same script detects `IS_WS_IFRAME` at startup and:

1. **Skips chrome init** (`connectWebSocket`, `loadMarkets`, `loadWatchlist`,
   `loadMovers`, `renderAlerts`) — visible only in the parent, waste in iframes.
   Without these guards a 4-widget dashboard = 5 WebSockets + 4× market polling.

2. **Hides chrome via CSS** — `#sidebar, #topbar, #cmdbar, #nav, #searchbar` all
   `display:none !important` inside iframes.

3. **Routes to the requested page** via `searchSymbol(wsSym)` (for markets),
   `loadIntraday()` (intraday), `loadCompare()` (compare with `?syms=`), or
   plain `navTo(page, groupMap[page])` for everything else.

When you add a new page that needs workspace support: add it to `WS_PAGES`,
add it to the iframe-mode `groupMap`, and (if symbol-aware) consider adding it
to `WS_SYMBOL_PAGES` or `WS_SYMS_PAGES`.

**Layout persistence**: every layout-changing call (`wsAddWidget`,
`wsRemoveWidget`, drag end, resize end, `wsSetSymbol`, `wsSetSyms`,
`wsLoadPreset`) calls `_wsSaveLayout()`. Shared links use `?layout=<base64>`
which overrides `localStorage` then writes itself back to it.

**Iframe size defaults** — `tallPages` (portfolio, brief, calendar, screeners,
fred) default to h=620; `widePages` (compare, correlation, heatmap) default to
w=760. If a new page's main content lands below the fold in a default widget,
add it to one of those sets.

---

## Known traps and gotchas

- **The portfolio uses `avgCost`, not `cost`.** Spreading `…pos` and then
  accessing `r.avgCost.toFixed(2)` will throw on legacy seeds.
- **Yahoo intraday timestamps are Eastern.** We convert to `America/Chicago`
  server-side and emit naive ISO so every viewer sees Central regardless of
  their browser zone. See `/intraday` and `/history`'s intraday branch.
- **Drag handler on widget headers** previously stole focus from inputs.
  `_wsAttachDrag` bails on `INPUT`, `BUTTON`, `SELECT` targets. Keep that bailout
  if you touch it.
- **FMP economic calendar is paywalled.** Don't re-attempt. Use FRED for
  previous/actual (no free forecasts exist anywhere — verified empirically).
- **Render's free tier is 0.1 CPU / 512 MB.** Cold endpoints over a few seconds
  feel broken. Cache aggressively. The Workspace dashboard with 6+ widgets is
  too heavy for free tier — recommend Starter ($7/mo).

---

## How to ship a change

```bash
# 1. edit server.py / index.html
# 2. test locally
uvicorn server:app --reload --port 8077
# 3. commit + push — Render auto-deploys
git add server.py index.html
git commit -m "concise summary

  More detail in the body if needed.
"
git push origin main
# 4. wait ~3-5 min, hard-refresh the live site (Cmd/Ctrl+Shift+R)
```

The two-file pattern (`server.py` + `index.html`) covers almost every change.
Add `requirements.txt` if you pull in a new Python lib.

---

## What's intentionally missing

Documenting these so you don't waste time looking:

- **No tests.** This is a small UI-driven project; tests rot fast in a codebase
  with no CI. Verify changes by running the dev server and using the feature.
- **No build step.** `index.html` is shipped raw. No webpack, no TS.
- **No backend DB.** Everything is localStorage on the client.
- **No login / user accounts.** The Workspace shareable URL is the closest thing
  to multi-user — and it's just a base64-encoded layout in a link.
- **No mobile/responsive layout.** Desktop only. If a future feature requires it,
  budget meaningfully — the page system uses `flex` and fixed-width widgets that
  would need rethinking.

---

## Recent painful bugs (lessons embedded in the code)

These are documented here so they're never re-introduced:

1. **Empty chart with no data** in Portfolio Perf → root cause was `/compare`
   crashing on a NaN value in DVN's normalized data. JSON serializer chokes on
   NaN. Fix: sanitize to `None` before return. Pattern applies anywhere we send
   pandas Series to JSON.

2. **"Future events with an actual"** in the Economic Calendar → old code
   stamped the latest BLS release onto *every* matching event including future
   ones. Plus the series IDs returned index levels (CPI 335%) not headline %
   changes. Fix: separate generated schedule from FRED enrichment; only attach
   actuals to the most recent past occurrence; compute MoM% / change correctly.

3. **Most Active tab stuck on "Loading…"** → two issues stacked: (a) `navTo`
   didn't call `loadMostActive` (only `showPage` did), and (b) the endpoint
   serialized 30 yfinance calls at 7+ seconds. Fix: wire into `navTo` + cache +
   `_parallel`. Same one-two-punch pattern likely lurks elsewhere; keep an eye.

4. **Inner widget header inputs not clickable** → drag-handler `mousedown`
   listener called `preventDefault()` unconditionally, stealing focus from any
   input inside the header. Fix: bail on interactive element targets. If you
   add new header controls, this bailout is what makes them work.
