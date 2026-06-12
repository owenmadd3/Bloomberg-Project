"""
Morning Research Brief — 6:00 AM CT
Modeled after Bloomberg Daybreak / Morning Brief format.

Sections:
  1. Overnight Market Wrap    — US futures, major indices (Asia/Europe), bonds, FX, commodities
  2. Key Economic Events Today — scheduled macro releases
  3. Earnings on Deck         — notable reports pre/post market
  4. Claude's Morning Call    — AI-generated daily thesis, themes, risks
"""

import os
import sys
import yfinance as yf
import anthropic
from datetime import date, datetime
import pytz

# ── API client ────────────────────────────────────────────────────────────────
_env = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env):
    from dotenv import load_dotenv
    load_dotenv(_env)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_groq_key = os.environ.get("GROQ_API_KEY")

# ── helpers ───────────────────────────────────────────────────────────────────

def safe_pct(val):
    if val is None or val != val:
        return "N/A"
    return f"{val:+.2f}%"

def safe_price(val, prefix="$"):
    if val is None or val != val:
        return "N/A"
    return f"{prefix}{val:,.2f}"

def divider(char="=", width=70):
    return char * width

def section(title, width=70):
    print(f"\n {title}")
    print(divider("=", width))

# ── 1. Overnight Market Wrap ─────────────────────────────────────────────────

FUTURES = {
    "S&P 500 Futures":  "ES=F",
    "Nasdaq Futures":   "NQ=F",
    "Dow Futures":      "YM=F",
    "Russell 2000 Fut": "RTY=F",
}

INTL_INDICES = {
    "Nikkei 225 (Japan)":   "^N225",
    "Hang Seng (HK)":       "^HSI",
    "Shanghai Comp (CN)":   "000001.SS",
    "FTSE 100 (UK)":        "^FTSE",
    "DAX (Germany)":        "^GDAXI",
    "CAC 40 (France)":      "^FCHI",
}

RATES_FX = {
    "10Y Treasury Yield":   "^TNX",
    "2Y Treasury Yield":    "^IRX",
    "US Dollar Index":      "DX-Y.NYB",
    "EUR/USD":              "EURUSD=X",
    "USD/JPY":              "JPY=X",
    "GBP/USD":              "GBPUSD=X",
}

COMMODITIES = {
    "WTI Crude Oil":   "CL=F",
    "Brent Crude":     "BZ=F",
    "Gold":            "GC=F",
    "Silver":          "SI=F",
    "Natural Gas":     "NG=F",
    "Bitcoin/USD":     "BTC-USD",
}

def fetch_quote_group(tickers: dict) -> list[dict]:
    results = []
    for name, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            price = getattr(info, "last_price", None)
            prev  = getattr(info, "previous_close", None)
            if price and prev and prev != 0:
                chg_pct = (price - prev) / prev * 100
            else:
                chg_pct = None
            results.append({"name": name, "symbol": sym, "price": price, "chg_pct": chg_pct})
        except Exception:
            results.append({"name": name, "symbol": sym, "price": None, "chg_pct": None})
    return results

def print_quote_group(rows: list[dict], price_prefix="$"):
    hdr = f"  {'Name':<26} {'Symbol':<12} {'Price':>11} {'Change':>9}"
    print(hdr)
    print("  " + divider("-", 62))
    for r in rows:
        price_str = safe_price(r["price"], prefix=price_prefix)
        chg_str   = safe_pct(r["chg_pct"])
        arrow = "▲" if (r["chg_pct"] or 0) > 0 else ("▼" if (r["chg_pct"] or 0) < 0 else " ")
        print(f"  {r['name']:<26} {r['symbol']:<12} {price_str:>11} {arrow}{chg_str:>8}")

def fetch_and_print_overnight():
    section("1 · OVERNIGHT MARKET WRAP")

    print("\n  US FUTURES")
    futures = fetch_quote_group(FUTURES)
    print_quote_group(futures)

    print("\n  ASIA / EUROPE INDICES")
    intl = fetch_quote_group(INTL_INDICES)
    print_quote_group(intl)

    print("\n  RATES & FX")
    rates = fetch_quote_group(RATES_FX)
    print_quote_group(rates)

    print("\n  COMMODITIES & CRYPTO")
    comms = fetch_quote_group(COMMODITIES)
    print_quote_group(comms)

    return futures, intl, rates, comms

# ── 2. Key Economic Events ────────────────────────────────────────────────────
# Hard-coded weekly calendar; Claude fills in significance in the narrative.

ECONOMIC_CALENDAR = {
    0: [  # Monday
        ("8:30 AM ET", "Fed Speaker (check Fed calendar)"),
        ("10:00 AM ET", "ISM Manufacturing PMI"),
    ],
    1: [  # Tuesday
        ("8:30 AM ET", "Trade Balance"),
        ("10:00 AM ET", "JOLTS Job Openings"),
        ("8:30 AM ET", "PPI (Producer Price Index)"),
    ],
    2: [  # Wednesday
        ("8:15 AM ET", "ADP Employment Change"),
        ("8:30 AM ET", "CPI (Consumer Price Index)"),
        ("10:00 AM ET", "ISM Services PMI"),
        ("2:00 PM ET",  "FOMC Minutes / Fed Decision (if scheduled)"),
    ],
    3: [  # Thursday
        ("8:30 AM ET", "Initial Jobless Claims"),
        ("8:30 AM ET", "Retail Sales"),
        ("8:30 AM ET", "Philadelphia Fed Manufacturing Index"),
    ],
    4: [  # Friday
        ("8:30 AM ET", "Nonfarm Payrolls & Unemployment Rate"),
        ("8:30 AM ET", "PCE Price Index"),
        ("10:00 AM ET", "University of Michigan Consumer Sentiment"),
    ],
}

def print_economic_events():
    section("2 · KEY ECONOMIC EVENTS TODAY")
    today_idx = date.today().weekday()
    events = ECONOMIC_CALENDAR.get(today_idx, [])
    if not events:
        print("  No major scheduled releases today (weekend / holiday).")
    else:
        print(f"  {'Time':<18} {'Release'}")
        print("  " + divider("-", 55))
        for time_str, release in events:
            print(f"  {time_str:<18} {release}")

# ── 3. Earnings on Deck ───────────────────────────────────────────────────────

def fetch_earnings_movers() -> tuple[list, list]:
    """Pull today's top gainers/losers as a proxy for earnings reaction."""
    gainers, losers = [], []
    try:
        import yfinance as yf
        # yfinance doesn't have a clean earnings-today API; use market movers as context
        screener_tickers = [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","BAC","GS",
            "WMT","HD","V","MA","UNH","LLY","XOM","CVX","PFE","MRK",
        ]
        movers = []
        for sym in screener_tickers:
            try:
                t = yf.Ticker(sym)
                fi = t.fast_info
                price = getattr(fi, "last_price", None)
                prev  = getattr(fi, "previous_close", None)
                if price and prev and prev != 0:
                    chg = (price - prev) / prev * 100
                    movers.append({"symbol": sym, "price": price, "chg_pct": chg})
            except Exception:
                pass

        movers.sort(key=lambda x: x["chg_pct"], reverse=True)
        gainers = movers[:3]
        losers  = sorted(movers, key=lambda x: x["chg_pct"])[:3]
    except Exception as e:
        print(f"  [earnings fetch error] {e}")
    return gainers, losers

def print_earnings_deck(gainers, losers):
    section("3 · LARGE-CAP MOVERS & EARNINGS REACTIONS")
    print("  (Top movers among major-cap watch list — potential earnings/news reactions)\n")

    print(f"  {'Symbol':<10} {'Price':>10} {'Move':>9}")
    print("  " + divider("-", 35))

    print("  -- Leaders --")
    for g in gainers:
        print(f"  {g['symbol']:<10} {safe_price(g['price']):>10} ▲{safe_pct(g['chg_pct']):>8}")

    print("  -- Laggards --")
    for l in losers:
        print(f"  {l['symbol']:<10} {safe_price(l['price']):>10} ▼{safe_pct(l['chg_pct']):>8}")

# ── 4. Claude's Morning Call ──────────────────────────────────────────────────

def build_brief_context(futures, intl, rates, comms, gainers, losers) -> str:
    ct = pytz.timezone("America/Chicago")
    now_ct = datetime.now(ct).strftime("%A, %B %d, %Y — %I:%M %p CT")

    lines = [f"Morning Research Brief — {now_ct}\n"]

    def fmt_group(label, rows):
        lines.append(f"{label}:")
        for r in rows:
            lines.append(f"  {r['name']} ({r['symbol']}): {safe_price(r['price'])} {safe_pct(r['chg_pct'])}")

    fmt_group("US Futures", futures)
    fmt_group("International Indices", intl)
    fmt_group("Rates & FX", rates)
    fmt_group("Commodities & Crypto", comms)

    lines.append("\nLarge-cap leaders today:")
    for g in gainers:
        lines.append(f"  {g['symbol']}: {safe_price(g['price'])} {safe_pct(g['chg_pct'])}")

    lines.append("Large-cap laggards today:")
    for l in losers:
        lines.append(f"  {l['symbol']}: {safe_price(l['price'])} {safe_pct(l['chg_pct'])}")

    return "\n".join(lines)

MORNING_CALL_PROMPT = """{context}

You are a senior macro analyst writing the pre-market research brief for a sophisticated institutional audience. This brief lands in their inbox at 6 AM CT, before the US open.

Write Claude's Morning Call in four tight blocks — no filler, no hedging boilerplate:

**THE OVERNIGHT PICTURE** (2–3 sentences)
Synthesize the futures, Asia/Europe, and commodity moves into one coherent macro narrative. What is the dominant overnight theme — risk-on/off, dollar strength, commodity stress, rates volatility?

**3 THEMES TO WATCH TODAY**
Numbered. Each theme: one bold headline phrase, then 1–2 sentences of substance. Draw on rates, sector rotation, geopolitics, or Fed policy as relevant.

**WHAT COULD SURPRISE THE MARKET**
One upside surprise scenario and one downside risk. Two sentences each.

**THE MORNING CALL**
One crisp paragraph — your overall read on how the trading day sets up. Which asset class or sector is most interesting, and what is the single most important data point or event to monitor.

Tone: confident, specific, analyst-grade. No disclaimers."""

def get_morning_call(context: str) -> str:
    prompt = MORNING_CALL_PROMPT.format(context=context)
    try:
        response = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as anthropic_err:
        if not _groq_key:
            raise
        # Fallback to Groq (llama3-70b) if Anthropic credits are exhausted
        try:
            from groq import Groq
            groq_client = Groq(api_key=_groq_key)
            resp = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=900,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content + "\n\n  [Generated via Groq/Llama3 fallback]"
        except Exception as groq_err:
            return f"  [Morning call unavailable — Anthropic: {anthropic_err} | Groq: {groq_err}]"

def print_morning_call(text: str):
    section("4 · CLAUDE'S MORNING CALL")
    print()
    for line in text.strip().split("\n"):
        print(f"  {line}")
    print()

# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ct = pytz.timezone("America/Chicago")
    now_ct = datetime.now(ct)

    print()
    print(divider("═", 70))
    print("  ◆  MORNING RESEARCH BRIEF")
    print(f"  {now_ct.strftime('%A, %B %d, %Y  |  %I:%M %p CT')}")
    print(divider("═", 70))

    print("\n  Fetching market data...")
    futures, intl, rates, comms = fetch_and_print_overnight()

    print_economic_events()

    print("\n  Scanning large-cap movers...")
    gainers, losers = fetch_earnings_movers()
    print_earnings_deck(gainers, losers)

    print("\n  Generating Claude's Morning Call...")
    context = build_brief_context(futures, intl, rates, comms, gainers, losers)
    morning_call = get_morning_call(context)
    print_morning_call(morning_call)

    print(divider("═", 70))
    print("  End of Morning Brief")
    print(divider("═", 70))
    print()
