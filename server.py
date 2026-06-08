from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import yfinance as yf
import requests
import pandas as pd
import numpy as np
import os
import time
import asyncio
import json
from functools import lru_cache
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
ai_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Simple time-based cache
_cache = {}
def cached(key, ttl=30):
    """Returns (data, hit) — hit=True means cached."""
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < ttl:
            return data, True
    return None, False

def set_cache(key, data):
    _cache[key] = (data, time.time())

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

# ── AI CHAT ──────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    symbol: str = ""
    history: list = []

@app.post("/ai/chat")
def ai_chat(req: ChatRequest):
    try:
        # Build context about the current stock if provided
        context = ""
        if req.symbol:
            try:
                info = yf.Ticker(req.symbol).info
                price  = info.get("currentPrice") or info.get("regularMarketPrice", "N/A")
                change = info.get("regularMarketChangePercent", 0)
                mcap   = info.get("marketCap", 0)
                pe     = info.get("trailingPE", "N/A")
                sector = info.get("sector", "N/A")
                name   = info.get("longName", req.symbol)
                context = f"""
Current stock context:
- Symbol: {req.symbol}
- Name: {name}
- Price: ${price} ({change:+.2f}%)
- Market Cap: ${mcap/1e9:.1f}B
- P/E Ratio: {pe}
- Sector: {sector}
"""
            except:
                context = f"Current symbol: {req.symbol}"

        system_prompt = f"""You are a professional financial analyst assistant built into a Bloomberg-style terminal.
You provide concise, data-driven analysis and insights about stocks, markets, and finance.
Be direct and professional. Use bullet points for clarity. Keep responses focused and under 200 words unless a detailed analysis is requested.
When asked about a specific stock, give actionable insights — key risks, catalysts, valuation context.
Never give explicit buy/sell advice, but you can discuss pros/cons and analyst sentiment.
{context}"""

        # Build message history
        messages = []
        for h in req.history[-10:]:  # last 10 messages for context
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": req.message})

        response = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1024,
            messages=[{"role": "system", "content": system_prompt}] + messages
        )
        return {"response": response.choices[0].message.content}
    except Exception as e:
        return {"response": f"Error: {str(e)}"}

# ── WEBSOCKET PRICE STREAM ────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: dict[WebSocket, set] = {}  # ws -> set of symbols

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections[ws] = set()

    def disconnect(self, ws: WebSocket):
        self.connections.pop(ws, None)

    def subscribe(self, ws: WebSocket, symbols: list):
        if ws in self.connections:
            self.connections[ws] = set(s.upper() for s in symbols)

    async def broadcast_prices(self):
        if not self.connections:
            return
        # Gather all unique symbols across all connections
        all_symbols = set()
        for syms in self.connections.values():
            all_symbols.update(syms)
        if not all_symbols:
            return

        prices = {}
        for sym in all_symbols:
            try:
                key = f"stock_{sym}"
                cached_data, hit = cached(key, ttl=60)
                if hit:
                    prices[sym] = {
                        "price":  cached_data.get("price", 0),
                        "change": cached_data.get("change", 0),
                        "change_abs": cached_data.get("change_abs", 0),
                    }
                else:
                    info = yf.Ticker(sym).info
                    p = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                    c = info.get("regularMarketChangePercent", 0) or 0
                    ca = info.get("regularMarketChange", 0) or 0
                    prices[sym] = {"price": round(p,2), "change": round(c,2), "change_abs": round(ca,2)}
            except:
                pass

        dead = []
        for ws, syms in self.connections.items():
            data = {s: prices[s] for s in syms if s in prices}
            if not data:
                continue
            try:
                await ws.send_text(json.dumps({"type": "prices", "data": data}))
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

manager = ConnectionManager()

@app.websocket("/ws/prices")
async def websocket_prices(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            msg = await asyncio.wait_for(ws.receive_text(), timeout=30)
            data = json.loads(msg)
            if data.get("type") == "subscribe":
                manager.subscribe(ws, data.get("symbols", []))
                # Send immediate price update
                await manager.broadcast_prices()
    except (WebSocketDisconnect, asyncio.TimeoutError, Exception):
        manager.disconnect(ws)

# Background task to push prices every 5 seconds
@app.on_event("startup")
async def start_price_broadcaster():
    asyncio.create_task(price_broadcast_loop())

async def price_broadcast_loop():
    while True:
        await asyncio.sleep(5)
        try:
            await manager.broadcast_prices()
        except:
            pass

INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "VIX": "^VIX",
    "10Y Treasury": "^TNX",
    "Oil (WTI)": "CL=F",
    "Gold": "GC=F",
    "BTC": "BTC-USD",
}

SCREENER_UNIVERSE = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","BRK-B","JPM","V",
    "UNH","XOM","JNJ","WMT","MA","PG","HD","CVX","MRK","LLY","AVGO","COST",
    "ABBV","PEP","KO","TMO","MCD","CSCO","ACN","DHR","ABT","NKE","NEE","TXN",
    "PM","MS","ADBE","CRM","AMD","INTC","QCOM","SBUX","BMY","RTX","GE","CAT",
    "BA","GS","BLK","SPGI","AXP","ISRG","SYK","ZTS","VRTX","REGN","CI","CB",
    "MMC","AON","PLD","AMT","CCI","EQIX","DLR","PSA","O","WFC","BAC","C",
    "USB","TFC","PNC","SCHW","CME","ICE","NDAQ","FIS","FISV","PYPL","SQ","COIN",
    "HOOD","UBER","LYFT","ABNB","DASH","SNAP","PINS","RBLX","U","DKNG",
    "F","GM","RIVN","NIO","TM","SPY","QQQ","DIA","IWM","GLD","TLT","HYG"
]

SECTOR_ETFS = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer Disc.": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Comm. Services": "XLC",
}

FOREX_PAIRS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X",
    "USD/CHF": "CHF=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "CAD=X",
    "EUR/GBP": "EURGBP=X",
    "USD/CNY": "CNY=X",
    "USD/MXN": "MXN=X",
    "EUR/JPY": "EURJPY=X",
}

TREASURIES = {
    "3M": "^IRX",
    "5Y": "^FVX",
    "10Y": "^TNX",
    "30Y": "^TYX",
}

# ── MARKETS ──────────────────────────────────────────────────
@app.get("/markets")
def get_markets():
    data, hit = cached("markets", ttl=60)
    if hit: return data
    results = []
    for name, symbol in INDICES.items():
        try:
            t = yf.Ticker(symbol)
            info = t.info
            price = info.get("regularMarketPrice") or info.get("currentPrice", 0)
            change = info.get("regularMarketChangePercent", 0)
            results.append({"name": name, "symbol": symbol, "price": round(price, 2), "change": round(change, 2)})
        except:
            results.append({"name": name, "symbol": symbol, "price": "N/A", "change": 0})
    set_cache("markets", results)
    return results

# ── STOCK ────────────────────────────────────────────────────
@app.get("/stock/{symbol}")
def get_stock(symbol: str):
    key = f"stock_{symbol}"
    data, hit = cached(key, ttl=30)
    if hit: return data
    ticker = yf.Ticker(symbol)
    info = ticker.info
    result = {
        "symbol": symbol.upper(),
        "name": info.get("longName", "N/A"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice", "N/A"),
        "prev_close": info.get("previousClose", "N/A"),
        "open": info.get("open", "N/A"),
        "change": round(info.get("regularMarketChangePercent", 0), 2),
        "change_abs": round(info.get("regularMarketChange", 0), 2),
        "market_cap": info.get("marketCap", "N/A"),
        "pe_ratio": info.get("trailingPE", "N/A"),
        "fwd_pe": info.get("forwardPE", "N/A"),
        "eps": info.get("trailingEps", "N/A"),
        "52w_high": info.get("fiftyTwoWeekHigh", "N/A"),
        "52w_low": info.get("fiftyTwoWeekLow", "N/A"),
        "volume": info.get("regularMarketVolume", "N/A"),
        "avg_volume": info.get("averageVolume", "N/A"),
        "dividend_yield": info.get("dividendYield", "N/A"),
        "beta": info.get("beta", "N/A"),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "description": info.get("longBusinessSummary", "N/A"),
        "day_high": info.get("dayHigh", "N/A"),
        "day_low": info.get("dayLow", "N/A"),
        "target_price": info.get("targetMeanPrice", "N/A"),
        "recommendation": info.get("recommendationKey", "N/A"),
        "revenue": info.get("totalRevenue", "N/A"),
        "profit_margin": info.get("profitMargins", "N/A"),
        "debt_to_equity": info.get("debtToEquity", "N/A"),
        "roe": info.get("returnOnEquity", "N/A"),
    }
    set_cache(key, result)
    return result

# ── HISTORY ──────────────────────────────────────────────────
@app.get("/history/{symbol}")
def get_history(symbol: str, period: str = "1mo"):
    key = f"history_{symbol}_{period}"
    data, hit = cached(key, ttl=60)
    if hit: return data
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period)
    result = {
        "dates": hist.index.strftime("%Y-%m-%d").tolist(),
        "close": hist["Close"].round(2).tolist(),
        "open": hist["Open"].round(2).tolist(),
        "high": hist["High"].round(2).tolist(),
        "low": hist["Low"].round(2).tolist(),
        "volume": hist["Volume"].tolist(),
    }
    set_cache(key, result)
    return result

# ── TECHNICAL INDICATORS ─────────────────────────────────────
@app.get("/indicators/{symbol}")
def get_indicators(symbol: str, period: str = "1y"):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=period)
    close = hist["Close"]
    dates = hist.index.strftime("%Y-%m-%d").tolist()

    def safe(series):
        return [None if pd.isna(v) else round(float(v), 2) for v in series]

    # Moving Averages
    ma20  = close.rolling(20).mean()
    ma50  = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    # Bollinger Bands (20-day, 2 std)
    std20  = close.rolling(20).std()
    bb_upper = ma20 + 2 * std20
    bb_lower = ma20 - 2 * std20

    # RSI (14-day)
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs    = gain / loss
    rsi   = 100 - (100 / (1 + rs))

    # MACD (12/26/9)
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist_m = macd - signal

    return {
        "dates":     dates,
        "close":     safe(close),
        "ma20":      safe(ma20),
        "ma50":      safe(ma50),
        "ma200":     safe(ma200),
        "bb_upper":  safe(bb_upper),
        "bb_lower":  safe(bb_lower),
        "rsi":       safe(rsi),
        "macd":      safe(macd),
        "signal":    safe(signal),
        "histogram": safe(hist_m),
    }

# ── NEWS ─────────────────────────────────────────────────────
@app.get("/news/{symbol}")
def get_news(symbol: str):
    ticker = yf.Ticker(symbol)
    news = ticker.news or []
    results = []
    for item in news[:10]:
        content = item.get("content", {})
        results.append({
            "title": content.get("title", item.get("title", "No title")),
            "publisher": content.get("provider", {}).get("displayName", item.get("publisher", "Unknown")),
            "link": content.get("canonicalUrl", {}).get("url", item.get("link", "#")),
            "time": content.get("pubDate", item.get("providerPublishTime", "")),
        })
    return results

@app.get("/market-news")
def get_market_news():
    symbols = ["SPY", "AAPL", "MSFT", "TSLA", "NVDA"]
    seen = set()
    results = []
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            for item in (ticker.news or []):
                content = item.get("content", {})
                title = content.get("title", item.get("title", ""))
                if title and title not in seen:
                    seen.add(title)
                    results.append({
                        "title": title,
                        "publisher": content.get("provider", {}).get("displayName", item.get("publisher", "Unknown")),
                        "link": content.get("canonicalUrl", {}).get("url", item.get("link", "#")),
                        "time": content.get("pubDate", ""),
                    })
        except:
            pass
    return results[:30]

# ── FINANCIALS ───────────────────────────────────────────────
@app.get("/financials/{symbol}")
def get_financials(symbol: str):
    ticker = yf.Ticker(symbol)
    def clean(df):
        if df is None or df.empty:
            return {}
        df = df.fillna(0)
        result = {}
        for col in df.columns[:4]:
            label = str(col)[:10]
            result[label] = {str(k): int(v) if isinstance(v, float) else v for k, v in df[col].items()}
        return result
    return {
        "income_stmt": clean(ticker.income_stmt),
        "balance_sheet": clean(ticker.balance_sheet),
        "cash_flow": clean(ticker.cashflow),
    }

# ── OPTIONS ──────────────────────────────────────────────────
@app.get("/options/{symbol}")
def get_options(symbol: str, expiry: str = ""):
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    if not expirations:
        return {"expirations": [], "calls": [], "puts": []}
    selected = expiry if expiry in expirations else expirations[0]
    chain = ticker.option_chain(selected)
    def fmt_chain(df):
        df = df.fillna(0)
        return df[["strike","lastPrice","bid","ask","volume","openInterest","impliedVolatility","inTheMoney"]].rename(
            columns={"lastPrice":"last","openInterest":"OI","impliedVolatility":"IV","inTheMoney":"ITM"}
        ).assign(IV=lambda d: (d["IV"]*100).round(1)).to_dict(orient="records")
    return {
        "expirations": list(expirations),
        "selected": selected,
        "calls": fmt_chain(chain.calls),
        "puts": fmt_chain(chain.puts),
    }

# ── SCREENER ─────────────────────────────────────────────────
@app.get("/screener")
def screener(
    sector: str = "",
    min_mcap: float = 0,
    max_pe: float = 9999,
    min_change: float = -100,
    max_change: float = 100,
    sort_by: str = "market_cap",
    limit: int = 50
):
    results = []
    for sym in SCREENER_UNIVERSE[:60]:
        try:
            t = yf.Ticker(sym)
            info = t.info
            s = info.get("sector", "")
            mcap = info.get("marketCap", 0) or 0
            pe = info.get("trailingPE", 0) or 0
            change = info.get("regularMarketChangePercent", 0) or 0
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            if sector and sector.lower() not in s.lower(): continue
            if mcap < min_mcap * 1e9: continue
            if pe > max_pe and pe != 0: continue
            if change < min_change or change > max_change: continue
            results.append({
                "symbol": sym, "name": info.get("shortName", sym), "sector": s,
                "price": round(price, 2), "change": round(change, 2), "market_cap": mcap,
                "pe_ratio": round(pe, 2) if pe else "N/A",
                "volume": info.get("regularMarketVolume", 0),
                "dividend_yield": round((info.get("dividendYield") or 0) * 100, 2),
            })
        except:
            pass
    sort_map = {
        "market_cap": lambda x: x["market_cap"],
        "change": lambda x: x["change"],
        "pe_ratio": lambda x: x["pe_ratio"] if isinstance(x["pe_ratio"], float) else 9999
    }
    results.sort(key=sort_map.get(sort_by, sort_map["market_cap"]), reverse=True)
    return results[:limit]

# ── ECONOMIC CALENDAR ────────────────────────────────────────
def fetch_bls_series(series_ids: list):
    """Fetch latest values from BLS public API (no key required)."""
    try:
        payload = {"seriesid": series_ids, "latest": True}
        r = requests.post(
            "https://api.bls.gov/publicAPI/v1/timeseries/data/",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        data = r.json()
        results = {}
        for series in data.get("Results", {}).get("series", []):
            sid = series["seriesID"]
            items = series.get("data", [])
            if len(items) >= 2:
                results[sid] = {
                    "actual":   items[0].get("value", ""),
                    "previous": items[1].get("value", ""),
                    "period":   items[0].get("periodName", "") + " " + items[0].get("year", ""),
                }
            elif len(items) == 1:
                results[sid] = {
                    "actual":   items[0].get("value", ""),
                    "previous": "",
                    "period":   items[0].get("periodName", "") + " " + items[0].get("year", ""),
                }
        return results
    except:
        return {}

# BLS Series IDs
BLS_SERIES = {
    "CPI (Consumer Price Index) MoM":    "CUUR0000SA0",
    "Core CPI MoM":                       "CUUR0000SA0L1E",
    "Non-Farm Payrolls":                  "CES0000000001",
    "Unemployment Rate":                  "LNS14000000",
    "PPI (Producer Price Index) MoM":    "WPUFD4",
    "Initial Jobless Claims":             "ICSA",
}

@app.get("/economic-calendar")
def get_economic_calendar():
    from datetime import datetime, timedelta
    import calendar

    today = datetime.now()
    events = []

    # ── FOMC Meeting dates 2026 ──────────────────────────────
    fomc_dates = [
        "2026-01-29", "2026-03-19", "2026-05-07",
        "2026-06-18", "2026-07-30", "2026-09-17",
        "2026-10-29", "2026-12-10",
    ]
    for d in fomc_dates:
        events.append({"date": d, "time": "14:00", "country": "USD",
            "title": "FOMC Interest Rate Decision", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})
        events.append({"date": d, "time": "14:30", "country": "USD",
            "title": "FOMC Press Conference", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})

    # ── Generate recurring monthly events for next 3 months ──
    for offset in range(3):
        month = (today.month + offset - 1) % 12 + 1
        year = today.year + (today.month + offset - 1) // 12
        _, days_in_month = calendar.monthrange(year, month)

        # Jobs Report — first Friday of month
        first_day = datetime(year, month, 1)
        days_until_friday = (4 - first_day.weekday()) % 7
        jobs_date = first_day + timedelta(days=days_until_friday)
        events.append({"date": jobs_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "Non-Farm Payrolls", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})
        events.append({"date": jobs_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "Unemployment Rate", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})

        # CPI — around 10th-14th of month (Wednesday)
        cpi_base = datetime(year, month, 10)
        days_to_wed = (2 - cpi_base.weekday()) % 7
        cpi_date = cpi_base + timedelta(days=days_to_wed)
        events.append({"date": cpi_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "CPI (Consumer Price Index) MoM", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})
        events.append({"date": cpi_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "Core CPI MoM", "impact": "High",
            "actual": "", "forecast": "", "previous": ""})

        # PPI — day after CPI
        ppi_date = cpi_date + timedelta(days=1)
        events.append({"date": ppi_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "PPI (Producer Price Index) MoM", "impact": "Medium",
            "actual": "", "forecast": "", "previous": ""})

        # Retail Sales — around 15th-17th
        retail_date = datetime(year, month, 15)
        events.append({"date": retail_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
            "title": "Retail Sales MoM", "impact": "Medium",
            "actual": "", "forecast": "", "previous": ""})

        # Initial Jobless Claims — every Thursday
        thursday = first_day + timedelta(days=(3 - first_day.weekday()) % 7)
        for week in range(4):
            claim_date = thursday + timedelta(weeks=week)
            if claim_date.month == month:
                events.append({"date": claim_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
                    "title": "Initial Jobless Claims", "impact": "Medium",
                    "actual": "", "forecast": "", "previous": ""})

        # GDP (quarterly — end of Jan, Apr, Jul, Oct)
        if month in [1, 4, 7, 10]:
            gdp_date = datetime(year, month, 30 if days_in_month >= 30 else days_in_month)
            events.append({"date": gdp_date.strftime("%Y-%m-%d"), "time": "08:30", "country": "USD",
                "title": "GDP Growth Rate QoQ (Advance)", "impact": "High",
                "actual": "", "forecast": "", "previous": ""})

        # ISM Manufacturing — first business day of month
        ism_date = first_day
        while ism_date.weekday() > 4:
            ism_date += timedelta(days=1)
        events.append({"date": ism_date.strftime("%Y-%m-%d"), "time": "10:00", "country": "USD",
            "title": "ISM Manufacturing PMI", "impact": "Medium",
            "actual": "", "forecast": "", "previous": ""})

    # ── Fetch upcoming earnings ──────────────────────────────
    for sym in ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "JPM", "BAC", "META", "V"]:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar
            if cal is not None and not cal.empty:
                earn_date = str(cal.columns[0])[:10] if hasattr(cal, 'columns') else ""
                if earn_date and earn_date > today.strftime("%Y-%m-%d"):
                    events.append({"date": earn_date, "time": "After Close", "country": "USD",
                        "title": f"{sym} Earnings Report", "impact": "High",
                        "actual": "", "forecast": "", "previous": ""})
        except:
            pass

    # Fetch real BLS data for actual + previous values
    bls_data = fetch_bls_series(list(BLS_SERIES.values()))
    series_lookup = {v: k for k, v in BLS_SERIES.items()}

    # Attach actual/previous to matching events
    for e in events:
        title = e["title"]
        if title in BLS_SERIES:
            sid = BLS_SERIES[title]
            if sid in bls_data:
                d = bls_data[sid]
                # Format nicely based on indicator type
                if "Payroll" in title:
                    actual = f"{float(d['actual']):,.0f}K" if d['actual'] else ""
                    prev   = f"{float(d['previous']):,.0f}K" if d['previous'] else ""
                elif "Rate" in title or "MoM" in title or "PMI" in title:
                    actual = f"{d['actual']}%" if d['actual'] else ""
                    prev   = f"{d['previous']}%" if d['previous'] else ""
                else:
                    actual = d['actual']
                    prev   = d['previous']
                e["actual"]   = actual
                e["previous"] = prev

    # Sort and filter to upcoming events only
    today_str = today.strftime("%Y-%m-%d")
    upcoming = [e for e in events if e["date"] >= today_str]
    upcoming = sorted(upcoming, key=lambda x: (x["date"], x["time"]))

    # Deduplicate
    seen = set()
    result = []
    for e in upcoming:
        key = (e["date"], e["title"])
        if key not in seen:
            seen.add(key)
            result.append(e)

    return result[:50]

# ── VOLATILITY ───────────────────────────────────────────────
@app.get("/volatility")
def get_volatility():
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="1y")
        closes = vix_hist["Close"].tolist()
        current = closes[-1] if closes else 0
        percentile = round(sum(1 for c in closes if c < current) / len(closes) * 100, 1) if closes else 0
        return {
            "current": round(current, 2),
            "percentile_1y": percentile,
            "high_1y": round(max(closes), 2) if closes else 0,
            "low_1y": round(min(closes), 2) if closes else 0,
            "avg_1y": round(sum(closes)/len(closes), 2) if closes else 0,
            "regime": "High Fear" if current > 30 else "Elevated" if current > 20 else "Normal" if current > 15 else "Low / Complacent"
        }
    except Exception as e:
        return {"error": str(e)}

# ── SECTOR HEATMAP ───────────────────────────────────────────
@app.get("/sector-heatmap")
def sector_heatmap():
    results = []
    for name, sym in SECTOR_ETFS.items():
        try:
            t = yf.Ticker(sym)
            info = t.info
            change = info.get("regularMarketChangePercent", 0) or 0
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            # get 1-week and 1-month change too
            hist = t.history(period="1mo")
            week_chg = 0
            month_chg = 0
            if len(hist) >= 5:
                week_chg = round((hist["Close"].iloc[-1] / hist["Close"].iloc[-5] - 1) * 100, 2)
            if len(hist) >= 20:
                month_chg = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2)
            results.append({
                "sector": name, "symbol": sym,
                "price": round(price, 2),
                "change_1d": round(change, 2),
                "change_1w": week_chg,
                "change_1m": month_chg,
            })
        except:
            results.append({"sector": name, "symbol": sym, "price": 0, "change_1d": 0, "change_1w": 0, "change_1m": 0})
    return results

# ── FOREX ────────────────────────────────────────────────────
@app.get("/forex")
def get_forex():
    results = []
    for pair, sym in FOREX_PAIRS.items():
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get("regularMarketPrice") or info.get("currentPrice", 0)
            change = info.get("regularMarketChangePercent", 0) or 0
            bid = info.get("bid", price)
            ask = info.get("ask", price)
            results.append({
                "pair": pair, "symbol": sym,
                "price": round(price, 4),
                "change": round(change, 3),
                "bid": round(bid, 4) if bid else round(price, 4),
                "ask": round(ask, 4) if ask else round(price, 4),
            })
        except:
            pass
    return results

# ── YIELD CURVE ──────────────────────────────────────────────
@app.get("/yield-curve")
def get_yield_curve():
    results = []
    for tenor, sym in TREASURIES.items():
        try:
            t = yf.Ticker(sym)
            info = t.info
            rate = info.get("regularMarketPrice") or info.get("currentPrice", 0)
            change = info.get("regularMarketChangePercent", 0) or 0
            results.append({"tenor": tenor, "rate": round(rate, 3), "change": round(change, 3)})
        except:
            pass
    return results

# ── ANALYST RATINGS ──────────────────────────────────────────
@app.get("/analysts/{symbol}")
def get_analysts(symbol: str):
    ticker = yf.Ticker(symbol)
    result = {}

    # Price targets
    try:
        targets = ticker.analyst_price_targets
        result["targets"] = {
            "current": targets.get("current", "N/A"),
            "mean":    targets.get("mean", "N/A"),
            "high":    targets.get("high", "N/A"),
            "low":     targets.get("low", "N/A"),
        }
    except:
        result["targets"] = {}

    # Recommendation trend
    try:
        rec = ticker.recommendations_summary
        if rec is not None and not rec.empty:
            result["recommendations"] = rec.head(4).to_dict(orient="records")
        else:
            result["recommendations"] = []
    except:
        result["recommendations"] = []

    # Upgrades / Downgrades
    try:
        upgrades = ticker.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            upgrades = upgrades.reset_index()
            upgrades["GradeDate"] = upgrades["GradeDate"].astype(str).str[:10]
            result["upgrades"] = upgrades.head(20).to_dict(orient="records")
        else:
            result["upgrades"] = []
    except:
        result["upgrades"] = []

    # EPS estimates
    try:
        eps = ticker.eps_trend
        if eps is not None and not eps.empty:
            result["eps_trend"] = eps.to_dict()
        else:
            result["eps_trend"] = {}
    except:
        result["eps_trend"] = {}

    return result

# ── EARNINGS HISTORY ─────────────────────────────────────────
@app.get("/earnings/{symbol}")
def get_earnings(symbol: str):
    ticker = yf.Ticker(symbol)
    result = {}

    # Historical EPS (earnings_history has: epsActual, epsEstimate, epsDifference, surprisePercent)
    try:
        hist = ticker.earnings_history
        if hist is not None and not hist.empty:
            hist = hist.reset_index()  # brings 'quarter' as a column
            rows = []
            for _, row in hist.iterrows():
                rows.append({
                    "quarter":        str(row.get("quarter", ""))[:10],
                    "epsActual":      float(row.get("epsActual", 0) or 0),
                    "epsEstimate":    float(row.get("epsEstimate", 0) or 0),
                    "epsDifference":  float(row.get("epsDifference", 0) or 0),
                    "surprisePercent":float(row.get("surprisePercent", 0) or 0),
                })
            result["history"] = rows[-12:]  # last 12 quarters
        else:
            result["history"] = []
    except Exception as e:
        result["history"] = []

    # Upcoming earnings dates
    try:
        dates = ticker.earnings_dates
        if dates is not None and not dates.empty:
            dates = dates.reset_index()
            dates.columns = [str(c) for c in dates.columns]
            upcoming = []
            for _, row in dates.head(4).iterrows():
                upcoming.append({k: str(v) for k, v in row.items()})
            result["upcoming"] = upcoming
        else:
            result["upcoming"] = []
    except:
        result["upcoming"] = []

    # Annual revenue + net income
    try:
        annual = ticker.income_stmt
        if annual is not None and not annual.empty:
            revenue    = annual.loc["Total Revenue"]    if "Total Revenue" in annual.index else None
            net_income = annual.loc["Net Income"]       if "Net Income" in annual.index else None
            cols = [str(c)[:10] for c in annual.columns[:4]]
            result["annual"] = {
                "years":      cols,
                "revenue":    [int(v) if not pd.isna(v) else 0 for v in (revenue.tolist()[:4] if revenue is not None else [])],
                "net_income": [int(v) if not pd.isna(v) else 0 for v in (net_income.tolist()[:4] if net_income is not None else [])],
            }
        else:
            result["annual"] = {}
    except:
        result["annual"] = {}

    return result

# ── INSTITUTIONAL + INSIDER ───────────────────────────────────
@app.get("/holders/{symbol}")
def get_holders(symbol: str):
    ticker = yf.Ticker(symbol)
    result = {}

    try:
        insider = ticker.insider_transactions
        if insider is not None and not insider.empty:
            rows = []
            for _, row in insider.head(20).iterrows():
                rows.append({
                    "insider":     str(row.get("Insider", "")),
                    "position":    str(row.get("Position", "")),
                    "transaction": str(row.get("Transaction", "")),
                    "shares":      int(row.get("Shares", 0) or 0),
                    "value":       float(row.get("Value", 0) or 0),
                    "date":        str(row.get("Start Date", ""))[:10],
                    "ownership":   str(row.get("Ownership", "")),
                })
            result["insider"] = rows
        else:
            result["insider"] = []
    except Exception as e:
        result["insider"] = []

    try:
        inst = ticker.institutional_holders
        if inst is not None and not inst.empty:
            rows = []
            for _, row in inst.head(15).iterrows():
                rows.append({
                    "holder":    str(row.get("Holder", "")),
                    "shares":    int(row.get("Shares", 0) or 0),
                    "value":     float(row.get("Value", 0) or 0),
                    "pctHeld":   float(row.get("pctHeld", 0) or 0),
                    "pctChange": float(row.get("pctChange", 0) or 0),
                    "date":      str(row.get("Date Reported", ""))[:10],
                })
            result["institutional"] = rows
        else:
            result["institutional"] = []
    except:
        result["institutional"] = []

    return result

# ── PEER COMPARISON ──────────────────────────────────────────
@app.get("/peers/{symbol}")
def get_peers(symbol: str):
    ticker = yf.Ticker(symbol)
    info = ticker.info
    sector = info.get("sector", "")
    # map sector to a curated peer list
    peer_map = {
        "Technology": ["AAPL","MSFT","GOOGL","META","NVDA","AMD","INTC","AVGO","ORCL","CRM"],
        "Healthcare": ["JNJ","UNH","PFE","ABBV","MRK","TMO","ABT","LLY","AMGN","GILD"],
        "Financial Services": ["JPM","BAC","WFC","GS","MS","C","BLK","SCHW","AXP","V"],
        "Consumer Cyclical": ["AMZN","TSLA","HD","MCD","NKE","SBUX","F","GM","BKNG","TJX"],
        "Energy": ["XOM","CVX","COP","SLB","EOG","PXD","MPC","VLO","PSX","OXY"],
        "Communication Services": ["GOOGL","META","NFLX","DIS","CMCSA","T","VZ","SNAP","PINS","RBLX"],
        "Industrials": ["CAT","GE","BA","RTX","HON","MMM","UPS","FDX","LMT","NOC"],
        "Consumer Defensive": ["WMT","PG","KO","PEP","COST","MDLZ","CL","KMB","GIS","MO"],
    }
    peers = peer_map.get(sector, ["SPY","QQQ","DIA"])
    results = []
    for sym in peers[:8]:
        try:
            t = yf.Ticker(sym)
            i = t.info
            results.append({
                "symbol": sym,
                "name": i.get("shortName", sym),
                "price": round(i.get("currentPrice") or i.get("regularMarketPrice", 0), 2),
                "change": round(i.get("regularMarketChangePercent", 0), 2),
                "market_cap": i.get("marketCap", 0),
                "pe_ratio": round(i.get("trailingPE", 0) or 0, 2),
                "ytd_return": round(i.get("52WeekChange", 0) or 0, 3),
            })
        except:
            pass
    return results

# ── SEC FILINGS ──────────────────────────────────────────────
@app.get("/sec-filings/{symbol}")
def get_sec_filings(symbol: str):
    try:
        # Get CIK from SEC ticker map
        ticker_map = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "bloomberg-clone admin@example.com"},
            timeout=10
        ).json()
        cik = None
        name = symbol
        for entry in ticker_map.values():
            if entry.get("ticker", "").upper() == symbol.upper():
                cik = str(entry["cik_str"]).zfill(10)
                name = entry.get("title", symbol)
                break
        if not cik:
            return {"filings": [], "error": "CIK not found"}

        # Fetch recent filings
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers={"User-Agent": "bloomberg-clone admin@example.com"},
            timeout=10
        ).json()

        recent = sub.get("filings", {}).get("recent", {})
        forms       = recent.get("form", [])
        dates       = recent.get("filingDate", [])
        accessions  = recent.get("accessionNumber", [])
        descriptions = recent.get("primaryDocument", [])

        target_forms = {"10-K", "10-Q", "8-K", "DEF 14A", "S-1"}
        filings = []
        for i, form in enumerate(forms):
            if form in target_forms and len(filings) < 25:
                acc = accessions[i].replace("-", "")
                doc = descriptions[i] if i < len(descriptions) else ""
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}"
                index_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"
                filings.append({
                    "form":   form,
                    "date":   dates[i] if i < len(dates) else "",
                    "url":    url,
                    "index":  index_url,
                    "accession": accessions[i],
                })
        return {"filings": filings, "company": name, "cik": cik}
    except Exception as e:
        return {"filings": [], "error": str(e)}

# ── PORTFOLIO RISK METRICS ────────────────────────────────────
@app.get("/portfolio/risk")
def portfolio_risk(symbols: str = "", weights: str = ""):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    wts  = [float(w) for w in weights.split(",") if w.strip()]
    if not syms:
        return {}
    if len(wts) != len(syms):
        wts = [1/len(syms)] * len(syms)

    try:
        # Fetch 1-year daily returns
        prices = {}
        for sym in syms:
            hist = yf.Ticker(sym).history(period="1y")["Close"]
            if not hist.empty:
                prices[sym] = hist

        if not prices:
            return {}

        import pandas as pd
        df = pd.DataFrame(prices).dropna()
        returns = df.pct_change().dropna()

        # Portfolio daily returns
        wt_arr = np.array(wts[:len(df.columns)])
        wt_arr = wt_arr / wt_arr.sum()
        port_returns = returns.values @ wt_arr

        # Metrics
        ann_return  = float(np.mean(port_returns) * 252)
        ann_vol     = float(np.std(port_returns) * np.sqrt(252))
        risk_free   = 0.05  # approximate
        sharpe      = float((ann_return - risk_free) / ann_vol) if ann_vol > 0 else 0

        # VaR (95% confidence, 1-day)
        var_95      = float(np.percentile(port_returns, 5))
        var_99      = float(np.percentile(port_returns, 1))

        # Max Drawdown
        cum = np.cumprod(1 + port_returns)
        peak = np.maximum.accumulate(cum)
        drawdown = (cum - peak) / peak
        max_dd  = float(np.min(drawdown))

        # Beta vs SPY
        spy_hist = yf.Ticker("SPY").history(period="1y")["Close"].pct_change().dropna()
        common_idx = returns.index.intersection(spy_hist.index)
        if len(common_idx) > 10:
            port_aligned = returns.loc[common_idx].values @ wt_arr
            spy_aligned  = spy_hist.loc[common_idx].values
            beta = float(np.cov(port_aligned, spy_aligned)[0,1] / np.var(spy_aligned))
        else:
            beta = 1.0

        return {
            "ann_return":  round(ann_return * 100, 2),
            "ann_vol":     round(ann_vol * 100, 2),
            "sharpe":      round(sharpe, 3),
            "var_95":      round(var_95 * 100, 3),
            "var_99":      round(var_99 * 100, 3),
            "max_drawdown":round(max_dd * 100, 2),
            "beta":        round(beta, 3),
        }
    except Exception as e:
        return {"error": str(e)}

# ── PORTFOLIO P&L HISTORY ────────────────────────────────────
@app.get("/portfolio/history")
def portfolio_history(symbols: str = "", shares: str = "", costs: str = "", period: str = "1y"):
    syms   = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    shrs   = [float(x) for x in shares.split(",") if x.strip()]
    csts   = [float(x) for x in costs.split(",") if x.strip()]
    if not syms or len(syms) != len(shrs):
        return {"dates": [], "values": [], "cost_basis": 0}

    try:
        prices = {}
        for sym in syms:
            hist = yf.Ticker(sym).history(period=period)["Close"]
            if not hist.empty:
                prices[sym] = hist

        df = pd.DataFrame(prices).dropna()
        if df.empty:
            return {"dates": [], "values": [], "cost_basis": 0}

        # Calculate portfolio value at each date
        values = []
        for _, row in df.iterrows():
            total = sum(row.get(sym, 0) * shrs[i] for i, sym in enumerate(syms) if sym in row)
            values.append(round(total, 2))

        cost_basis = sum(shrs[i] * csts[i] for i in range(len(syms)))

        return {
            "dates":      df.index.strftime("%Y-%m-%d").tolist(),
            "values":     values,
            "cost_basis": round(cost_basis, 2),
        }
    except Exception as e:
        return {"dates": [], "values": [], "cost_basis": 0, "error": str(e)}

# ── CORRELATION MATRIX ────────────────────────────────────────
@app.get("/correlation")
def correlation_matrix(symbols: str = "", period: str = "1y"):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:15]
    if len(syms) < 2:
        return {"symbols": [], "matrix": []}
    try:
        prices = {}
        for sym in syms:
            hist = yf.Ticker(sym).history(period=period)["Close"]
            if not hist.empty:
                prices[sym] = hist

        df = pd.DataFrame(prices).dropna()
        if df.shape[1] < 2:
            return {"symbols": [], "matrix": []}

        returns = df.pct_change().dropna()
        corr = returns.corr().round(3)
        syms_out = list(corr.columns)
        matrix = corr.values.tolist()
        return {"symbols": syms_out, "matrix": matrix}
    except Exception as e:
        return {"symbols": [], "matrix": [], "error": str(e)}

# ── 52-WEEK HIGH/LOW SCREENER ─────────────────────────────────
@app.get("/screener/52week")
def screener_52week(mode: str = "high", threshold: float = 2.0):
    """mode: 'high' = near 52w high, 'low' = near 52w low. threshold = % away"""
    results = []
    for sym in SCREENER_UNIVERSE[:80]:
        try:
            t = yf.Ticker(sym)
            info = t.info
            price   = info.get("currentPrice") or info.get("regularMarketPrice", 0) or 0
            high52  = info.get("fiftyTwoWeekHigh", 0) or 0
            low52   = info.get("fiftyTwoWeekLow", 0) or 0
            change  = info.get("regularMarketChangePercent", 0) or 0
            volume  = info.get("regularMarketVolume", 0) or 0
            avg_vol = info.get("averageVolume", 1) or 1

            if not price or not high52 or not low52:
                continue

            pct_from_high = round((price - high52) / high52 * 100, 2)
            pct_from_low  = round((price - low52)  / low52  * 100, 2)

            if mode == "high" and pct_from_high >= -threshold:
                results.append({
                    "symbol": sym,
                    "name": info.get("shortName", sym),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "52w_high": round(high52, 2),
                    "52w_low": round(low52, 2),
                    "pct_from_high": pct_from_high,
                    "pct_from_low": round(pct_from_low, 2),
                    "volume": volume,
                    "rel_volume": round(volume / avg_vol, 2),
                    "sector": info.get("sector", ""),
                })
            elif mode == "low" and pct_from_low <= threshold:
                results.append({
                    "symbol": sym,
                    "name": info.get("shortName", sym),
                    "price": round(price, 2),
                    "change": round(change, 2),
                    "52w_high": round(high52, 2),
                    "52w_low": round(low52, 2),
                    "pct_from_high": pct_from_high,
                    "pct_from_low": round(pct_from_low, 2),
                    "volume": volume,
                    "rel_volume": round(volume / avg_vol, 2),
                    "sector": info.get("sector", ""),
                })
        except:
            pass

    sort_key = "pct_from_high" if mode == "high" else "pct_from_low"
    results.sort(key=lambda x: x[sort_key], reverse=(mode == "high"))
    return results[:40]

# ── PORTFOLIO QUOTE ──────────────────────────────────────────
@app.get("/portfolio/quotes")
def portfolio_quotes(symbols: str = ""):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = {}
    for sym in syms:
        # Use stock cache if available (30s TTL)
        key = f"stock_{sym}"
        cached_data, hit = cached(key, ttl=30)
        if hit:
            results[sym] = {
                "price": cached_data.get("price", 0),
                "change": cached_data.get("change", 0),
                "name": cached_data.get("name", sym),
            }
            continue
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            change = info.get("regularMarketChangePercent", 0) or 0
            results[sym] = {
                "price": round(price, 2),
                "change": round(change, 2),
                "name": info.get("shortName", sym),
            }
        except:
            results[sym] = {"price": 0, "change": 0, "name": sym}
    return results

# ── INTRADAY CHART ───────────────────────────────────────────
@app.get("/intraday/{symbol}")
def get_intraday(symbol: str, interval: str = "5m"):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="1d", interval=interval)
    if hist.empty:
        hist = ticker.history(period="5d", interval="15m")
    return {
        "times":  hist.index.strftime("%H:%M").tolist(),
        "close":  hist["Close"].round(2).tolist(),
        "open":   hist["Open"].round(2).tolist(),
        "high":   hist["High"].round(2).tolist(),
        "low":    hist["Low"].round(2).tolist(),
        "volume": hist["Volume"].tolist(),
    }

# ── MULTI SECURITY COMPARISON ────────────────────────────────
@app.get("/compare")
def compare_securities(symbols: str = "", period: str = "1y"):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:20]
    result = {}
    for sym in syms:
        try:
            hist = yf.Ticker(sym).history(period=period)["Close"]
            # Normalize to % return from start
            base = hist.iloc[0]
            normalized = ((hist / base - 1) * 100).round(2).tolist()
            result[sym] = {
                "dates":      hist.index.strftime("%Y-%m-%d").tolist(),
                "normalized": normalized,
                "raw":        hist.round(2).tolist(),
            }
        except:
            pass
    return result

# ── MOST ACTIVE ───────────────────────────────────────────────
@app.get("/most-active")
def most_active():
    symbols = [
        "AAPL","MSFT","NVDA","TSLA","AMZN","META","GOOGL","AMD","INTC","PLTR",
        "BAC","F","AAL","CCL","SOFI","NIO","RIVN","AMC","GME","SPY","QQQ","SOXL",
        "TQQQ","SPXL","JPM","VZ","T","PFE","HOOD","COIN","MARA","RIOT"
    ]
    results = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.info
            vol = info.get("regularMarketVolume", 0) or 0
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            change = info.get("regularMarketChangePercent", 0) or 0
            avg_vol = info.get("averageVolume", 1) or 1
            results.append({
                "symbol": sym,
                "price":  round(price, 2),
                "change": round(change, 2),
                "volume": vol,
                "avg_volume": avg_vol,
                "rel_volume": round(vol / avg_vol, 2) if avg_vol else 0,
                "name": info.get("shortName", sym),
            })
        except:
            pass
    results.sort(key=lambda x: x["volume"], reverse=True)
    return results[:20]

# ── PRE/AFTER MARKET QUOTES ───────────────────────────────────
@app.get("/allq/{symbol}")
def get_allq(symbol: str):
    ticker = yf.Ticker(symbol)
    info = ticker.info
    return {
        "symbol":          symbol.upper(),
        "name":            info.get("longName", ""),
        "regular_price":   info.get("currentPrice") or info.get("regularMarketPrice", "N/A"),
        "regular_change":  round(info.get("regularMarketChangePercent", 0), 2),
        "pre_price":       info.get("preMarketPrice", "N/A"),
        "pre_change":      round(info.get("preMarketChangePercent", 0) or 0, 2),
        "post_price":      info.get("postMarketPrice", "N/A"),
        "post_change":     round(info.get("postMarketChangePercent", 0) or 0, 2),
        "bid":             info.get("bid", "N/A"),
        "ask":             info.get("ask", "N/A"),
        "bid_size":        info.get("bidSize", "N/A"),
        "ask_size":        info.get("askSize", "N/A"),
        "open":            info.get("open", "N/A"),
        "prev_close":      info.get("previousClose", "N/A"),
        "day_high":        info.get("dayHigh", "N/A"),
        "day_low":         info.get("dayLow", "N/A"),
        "volume":          info.get("regularMarketVolume", "N/A"),
        "avg_volume":      info.get("averageVolume", "N/A"),
        "market_cap":      info.get("marketCap", "N/A"),
        "52w_high":        info.get("fiftyTwoWeekHigh", "N/A"),
        "52w_low":         info.get("fiftyTwoWeekLow", "N/A"),
    }

# ── MOVERS ───────────────────────────────────────────────────
@app.get("/movers")
def get_movers():
    symbols = [
        "AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","BRK-B",
        "JPM","V","UNH","XOM","JNJ","WMT","MA","PG","HD","CVX","MRK","LLY"
    ]
    results = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.info
            price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
            change = info.get("regularMarketChangePercent", 0)
            results.append({"symbol": sym, "price": round(price, 2), "change": round(change, 2)})
        except:
            pass
    gainers = sorted(results, key=lambda x: x["change"], reverse=True)[:5]
    losers  = sorted(results, key=lambda x: x["change"])[:5]
    return {"gainers": gainers, "losers": losers}
