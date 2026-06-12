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

The app uses two paid AI/data keys. They are **not** stored in the code (on purpose).
They live in the Render dashboard under the service's **Environment** tab:

| Key | What it powers | Where to get a replacement |
| --- | --- | --- |
| `GROQ_API_KEY` | The AI chat assistant | https://console.groq.com (free tier available) |
| `ANTHROPIC_API_KEY` | The deeper AI analysis | https://console.anthropic.com |

The keys currently in use belong to the intern's personal accounts. **After the intern
leaves, the company should create its own keys** at the links above and paste them into
the Render Environment tab (then click *Manual Deploy → Deploy*). The old keys will stop
working once the intern's accounts are closed.

---

## How to deploy it from scratch (≈5 minutes, no coding)

1. Make sure the code is in a GitHub repo the company controls (see step 1 above).
2. Sign in to **https://render.com** with the company account.
3. Click **New → Blueprint**.
4. Connect the GitHub repo and select it. Render automatically finds `render.yaml` in
   the repo and sets everything up — build command, start command, Python version.
5. Render will prompt for the two secret values: paste in `GROQ_API_KEY` and
   `ANTHROPIC_API_KEY`.
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
