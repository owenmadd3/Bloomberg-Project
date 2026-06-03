import anthropic
from openbb import obb
from datetime import date

client = anthropic.Anthropic()

# ── helpers ──────────────────────────────────────────────────────────────────

def safe_pct(val):
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"

def safe_price(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"

# ── top gainers / losers ─────────────────────────────────────────────────────

def fetch_movers():
    gainers, losers = [], []
    try:
        g = obb.equity.market.gainers(source="yfinance")
        for r in (g.results or [])[:5]:
            gainers.append({
                "symbol": r.symbol,
                "name": (r.name or r.symbol)[:28],
                "price": r.price,
                "change_pct": r.percent_change,
            })
    except Exception as e:
        print(f"  [gainers error] {e}")

    try:
        l = obb.equity.market.losers(source="yfinance")
        for r in (l.results or [])[:5]:
            losers.append({
                "symbol": r.symbol,
                "name": (r.name or r.symbol)[:28],
                "price": r.price,
                "change_pct": r.percent_change,
            })
    except Exception as e:
        print(f"  [losers error] {e}")

    return gainers, losers

def print_movers(gainers, losers):
    width = 65
    row = f"{'Name':<30} {'Symbol':<8} {'Price':>9} {'Change':>10}"
    divider = "-" * width

    print("\n TOP GAINERS TODAY")
    print("=" * width)
    print(row)
    print(divider)
    if gainers:
        for g in gainers:
            print(f"{g['name']:<30} {g['symbol']:<8} {safe_price(g['price']):>9} {safe_pct(g['change_pct']):>10}")
    else:
        print("  No data available.")

    print("\n TOP LOSERS TODAY")
    print("=" * width)
    print(row)
    print(divider)
    if losers:
        for l in losers:
            print(f"{l['name']:<30} {l['symbol']:<8} {safe_price(l['price']):>9} {safe_pct(l['change_pct']):>10}")
    else:
        print("  No data available.")

# ── Claude's top picks ───────────────────────────────────────────────────────

def build_context(gainers, losers):
    lines = [f"Today is {date.today().strftime('%B %d, %Y')} (market close)."]
    if gainers:
        lines.append("\nToday's top gainers:")
        for g in gainers:
            lines.append(f"  {g['symbol']} ({g['name']}): {safe_pct(g['change_pct'])} at {safe_price(g['price'])}")
    if losers:
        lines.append("\nToday's top losers:")
        for l in losers:
            lines.append(f"  {l['symbol']} ({l['name']}): {safe_pct(l['change_pct'])} at {safe_price(l['price'])}")
    return "\n".join(lines)

def get_claude_picks(gainers, losers):
    context = build_context(gainers, losers)

    prompt = f"""{context}

You are a sharp equity analyst writing a concise end-of-day market close note.

Pick 2–3 stocks (they don't have to be from the movers list — use your own knowledge of upcoming catalysts, earnings, macro events, or sector rotation) that you think have a good chance of seeing notable price movement TOMORROW.

For each pick, write:
- Ticker and company name
- One punchy thesis sentence (why it might move)
- Key catalyst or risk to watch

Keep each pick to 3–4 lines max. Write in a confident but factual analyst tone. No disclaimers or legal boilerplate."""

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text

def print_claude_picks(picks_text):
    width = 65
    print("\n CLAUDE'S TOP PICKS FOR TOMORROW")
    print("=" * width)
    print("  Stocks to watch at tomorrow's open\n")
    for line in picks_text.strip().split("\n"):
        print(f"  {line}")
    print()

# ── main ─────────────────────────────────────────────────────────────────────

print("\nMARKET CLOSE REPORT")
print("=" * 65)
print(f"  {date.today().strftime('%A, %B %d, %Y')}")

print("\n  Fetching market movers...")
gainers, losers = fetch_movers()
print_movers(gainers, losers)

print("\n  Generating Claude's top picks...")
picks = get_claude_picks(gainers, losers)
print_claude_picks(picks)
