# Bloomberg Terminal — Hosting & Handoff Guide

This is the live financial terminal site (a single-page web app backed by a Python
server). This document explains how it's hosted so it keeps running **without anyone's
personal laptop being on**, and how to take ownership of it.

The app is two parts that run together as one service:

- **`server.py`** — the backend (FastAPI). Pulls market data, runs the AI chat, and
  streams live prices.
- **`index.html`** — the frontend (the terminal UI you see in the browser).

It is hosted on **Render** (https://render.com), which runs `server.py` 24/7 and gives
the site a permanent web address.

---

## ⚠️ FIRST PRIORITY: take ownership before the intern leaves

Right now both the code and (likely) the hosting account are under a personal account.
If nothing changes, the site can stop working once that account goes dormant. Do these
two transfers **before the internship ends**:

1. **The code (GitHub):** the repo is at
   `https://github.com/owenmadd3/Bloomberg-Project`.
   Either transfer it to a company GitHub organization (GitHub → repo **Settings** →
   *Transfer ownership*), or have the company create its own account and fork/clone it
   there. Render deploys from whichever repo the company controls.

2. **The hosting (Render):** create the Render service under a **company-owned login**
   (a shared company email, not a personal one). If it was first set up under a personal
   account, the cleanest path is to redeploy it fresh under the company account using the
   steps below — it takes ~5 minutes.

If you only do one thing from this document, do this.

---

## The API keys (the site needs these to work)

The app uses these API keys. They are **not** stored in the code (on purpose). They live
in the Render dashboard under the service's **Environment** tab:

| Key | What it powers | Required? | Where to get one |
| --- | --- | --- | --- |
| `GROQ_API_KEY` | The AI chat assistant | Yes | https://console.groq.com (free tier) |
| `ANTHROPIC_API_KEY` | The deeper AI analysis | Yes | https://console.anthropic.com |
| `FRED_API_KEY` | Previous / actual numbers on the Economic Calendar | Optional | https://fredaccount.stlouisfed.org (free, instant) |

Without `FRED_API_KEY`, the Economic Calendar still shows the upcoming schedule — it just
leaves the number columns blank. (Consensus *forecasts* aren't available from any free
source, so the forecast column stays blank regardless.)

The keys currently in use belong to the intern's personal accounts. **After the intern
leaves, the company should create its own keys** at the links above and paste them into
the Render Environment tab (then click *Manual Deploy → Deploy*). The old keys will stop
working once the intern's accounts are closed.

---

## The quarterly BIS debt email (Global Debt page)

The site has a **Global Debt** page (Macro menu) showing the BIS Total
Non-Financial Debt-to-GDP table — pre-COVID (4Q 2019) vs the latest quarter, for
10 economies. The same table is **emailed automatically to a recipient list when
BIS publishes a new quarter** (roughly 4 times a year; BIS data is quarterly, not
monthly). No signup page or database — the recipient list is a single secret.

**How it works (no server involved):**

- The page reads the live `/bis-debt` endpoint in `server.py`, which pulls the
  data from the BIS Data Portal (no API key needed).
- The email is sent by `bis_email.py`, run on a schedule by a **free GitHub
  Actions workflow** (`.github/workflows/bis-email.yml`) — *not* by Render. The
  workflow runs daily, but only actually emails when a genuinely new quarter
  appears (it remembers the last one sent in `bis_state.json`). On all other days
  it's a no-op.
- Emails are sent through **Gmail SMTP** from a dedicated Gmail account.
  Recipients are BCC'd, so they never see each other's addresses. (Gmail caps
  sends at ~500 recipients/day — far above this list's size.)

**One-time setup (do this to turn the emails on):**

1. Create (or pick) a Gmail account to send from, e.g. `globaldebtbrief@gmail.com`.
2. On that Google account: turn on **2-Step Verification**, then generate an
   **App Password** (Google Account → Security → 2-Step Verification → App
   passwords). It's a 16-character code — this is what the workflow logs in with,
   *not* the normal Gmail password.
3. In GitHub → repo **Settings → Secrets and variables → Actions → New repository
   secret**, add these secrets:

   | Secret | Value |
   | --- | --- |
   | `GMAIL_ADDRESS` | the sending Gmail, e.g. `globaldebtbrief@gmail.com` |
   | `GMAIL_APP_PASSWORD` | the 16-char app password from step 2 |
   | `BIS_EMAIL_RECIPIENTS` | comma-separated recipient emails |
   | `BIS_EMAIL_FROM` | *(optional)* display name, e.g. `Global Debt <globaldebtbrief@gmail.com>`. Defaults to `GMAIL_ADDRESS` if omitted. |

4. To add or remove a recipient later, just edit the `BIS_EMAIL_RECIPIENTS`
   secret — nothing else changes.
5. To test it immediately: GitHub → **Actions → BIS debt email → Run workflow**,
   tick **force**. That sends the current quarter to the list regardless of
   whether it's new. (Leave force off for the normal scheduled behavior.)

**⚠️ Ownership note (same as the API keys):** the sending Gmail account is
currently the intern's. Before the internship ends, the company should create its
**own** sending account (a company Gmail/Workspace address), generate a fresh app
password, and replace the `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `BIS_EMAIL_FROM`
secrets. The recipient list lives only in the `BIS_EMAIL_RECIPIENTS` secret — copy
it over too.

**Good to know:** when a new quarter is emailed, the workflow commits the updated
`bis_state.json` back to the repo, which triggers a normal Render redeploy. That's
expected and harmless (it happens ~4 times a year).

**Keepalive (why there's a monthly "heartbeat" commit):** GitHub automatically
disables scheduled workflows after 60 days with no commits to the repo. BIS
quarters are ~90 days apart, so a second workflow
(`.github/workflows/keepalive.yml`) makes one tiny commit on the 1st of each
month to keep the repo active — otherwise the email schedule could get paused
between quarters. You'll see monthly `chore: keepalive heartbeat` commits (and a
matching ~50s Render redeploy); both are expected and harmless. If you ever do
get a GitHub email saying a workflow was disabled for inactivity, just click
**Enable workflow** on the Actions tab.

---

## How to deploy it from scratch (≈5 minutes, no coding)

1. Make sure the code is in a GitHub repo the company controls (see step 1 above).
2. Sign in to **https://render.com** with the company account.
3. Click **New → Blueprint**.
4. Connect the GitHub repo and select it. Render automatically finds `render.yaml` in
   the repo and sets everything up — build command, start command, Python version.
5. Render will prompt for the secret values: paste in `GROQ_API_KEY` and
   `ANTHROPIC_API_KEY` (and optionally `FRED_API_KEY` for the calendar's numbers).
6. Click **Apply / Create**. First build takes a few minutes. When it finishes, Render
   shows a URL like `https://bloomberg-terminal.onrender.com` — that's the live site.
   Send that link to whoever needs it.

That's it. The site now runs on Render's servers, not anyone's laptop.

---

## Make it always-on (recommended for a boss-facing site)

The default plan in `render.yaml` is **free**, which is fine for a demo — but a free
service **goes to sleep after ~15 minutes of no visitors**, and the next visitor waits
~50 seconds for it to wake up (it can look broken during that wait).

To remove that delay: in the Render dashboard, open the service → **Settings** →
**Instance Type** → choose **Starter (~$7/month)**. Nothing in the code changes; it just
stays awake.

---

## Updating the site later

Render auto-redeploys whenever new code is pushed to the connected GitHub repo's main
branch. To deploy a change: push to GitHub, and Render rebuilds automatically. You can
also force a rebuild from the dashboard with **Manual Deploy → Deploy latest commit**.

---

## Good to know

- **Live prices** stream over a WebSocket; Render supports this on all plans. On the free
  plan the stream pauses when the service sleeps and reconnects automatically on the next
  visit.
- **Disk is temporary.** The app caches market data to disk to load faster, and that
  cache resets on each redeploy. That's harmless — it just rebuilds the cache. Don't rely
  on the server's local files for permanent storage.
- **This is the deployed site.** The repo also contains `app.py`, a *separate* Streamlit
  research tool that is **not** part of this website. Deploying that is unrelated to this
  guide.

---

## Operations playbook (when things break)

Most-likely problems, ranked by how often they actually happen, and how to fix each in under
5 minutes from the Render dashboard.

### "The site is slow / 'Loading…' forever"

The free plan sleeps after ~15 minutes of no traffic. The first visitor after a quiet stretch
waits ~50 seconds for it to wake. **This is not a bug** — it's the free tier.

- **Quick check**: refresh the site twice. The first load wakes it; the second is fast.
- **Real fix**: upgrade to Starter ($7/mo) in Render → `bloomberg-terminal` → **Settings →
  Instance Type**. Always-on, no cold start. Strongly recommended for a customer-facing site.

### "The page returns 502 Bad Gateway"

Almost always a transient deploy or cold-start blip.

- **Wait 30 seconds and refresh.** Render replaces instances during deploys; there's a brief
  window where the gateway has nothing to route to.
- If it persists for more than ~2 minutes, check the next section.

### "The site is down / red status in Render"

1. Render dashboard → `bloomberg-terminal` → **Events** tab. Find the latest entry.
   - "Deploy failed" → click into the build log, look for the error (usually a Python
     dependency mismatch or a syntax error in a recent commit).
   - "Service crashed" → click **Logs** to see the stack trace.
2. **Fastest recovery**: in **Manual Deploy** (top right), pick the last known-good commit
   (one that previously said "Deploy live") and click **Deploy**.

### "The AI features stopped working"

The Groq or Anthropic API key has likely expired or been revoked.

1. Test which one is dead: open the live site → try the **AI Chat** (Groq) and the
   **Morning Brief** (Anthropic). Whichever errors is the dead key.
2. Get a new key at the appropriate console (links in the API keys table above).
3. Render → `bloomberg-terminal` → **Environment** → edit the variable → save.
4. Render auto-redeploys; takes ~3 minutes.

### "The Economic Calendar numbers are blank"

`FRED_API_KEY` is missing or invalid. Numbers go blank, the schedule itself still shows.

- Get a new free key at https://fredaccount.stlouisfed.org/apikeys (instant approval).
- Paste it into Render's Environment tab as `FRED_API_KEY`.

### "All the market data is broken / shows 'N/A'"

Yahoo Finance is rate-limiting the server, or their service is down. There's no fix on our
side; this is upstream. It usually clears within an hour. If it lasts longer than a day, the
app's `yfinance` dependency may need a version bump — that's a developer task (see CLAUDE.md).

### Verifying a deploy went out

1. Render → Events → look for "Deploy live for `<commit hash>`".
2. Compare to the latest GitHub commit hash at
   https://github.com/owenmadd3/Bloomberg-Project/commits/main (or wherever the repo
   has been transferred to).
3. **If they match** → the new code is live. Hard-refresh the browser (Cmd/Ctrl+Shift+R)
   to make sure you're not seeing a cached page.
4. **If they don't match** → Render's still building. Wait or check the build log.

### Manual smoke check (after any deploy)

A 60-second sanity pass to confirm nothing's broken:

1. Site loads at the URL (no 502, no 500).
2. Top markets ticker (S&P / NASDAQ / DOW) shows numbers, not "N/A".
3. Type a ticker (e.g. AAPL) in the search box → click GO → stock data + chart appear.
4. Click **AI Chat** → ask "what is AAPL's PE?" → reply appears (proves Groq is up).
5. Click **Markets → Workspace** → the dashboard renders with at least one widget.

If all five pass, the site is healthy.

---

## Disaster recovery

The codebase is on GitHub. Even if the Render service is deleted, the company can redeploy
the whole site from a fresh Render account in ~5 minutes using the steps above ("How to
deploy it from scratch"). Nothing is lost.

The only thing that lives outside of Git is **environment variables** (API keys). Keep those
in a password manager.
