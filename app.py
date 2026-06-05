import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime, timedelta
from plotly.subplots import make_subplots
import pandas as pd
import json
import os
import re
import requests
import time
import pickle
import hashlib
from difflib import get_close_matches

# ── Shared disk cache (shared with all apps to reduce Yahoo Finance requests) ──
_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".yf_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_get(key, ttl):
    path = os.path.join(_CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".pkl")
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < ttl:
            try:
                with open(path, "rb") as f:
                    return True, pickle.load(f)
            except Exception:
                pass
    return False, None

def _cache_set(key, value):
    path = os.path.join(_CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".pkl")
    try:
        with open(path, "wb") as f:
            pickle.dump(value, f)
    except Exception:
        pass

def _yf_with_retry(fn, retries=5, base_delay=4):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            if "too many requests" in msg or "rate limit" in msg or "429" in msg:
                if attempt < retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
            raise
    raise RuntimeError("Rate limited by Yahoo Finance — please wait a moment and try again.")
st.set_page_config(
    page_title="Mini Bloomberg",
    page_icon=None,
    layout="wide",
)

# ── Persistence ───────────────────────────────────────────────────────────────
WATCHLIST_FILE    = os.path.join(os.path.dirname(__file__), "watchlist.json")
PICKS_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "picks_history.json")

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return []

def save_watchlist(wl):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(wl, f)

def load_picks_history():
    if os.path.exists(PICKS_HISTORY_FILE):
        with open(PICKS_HISTORY_FILE) as f:
            return json.load(f)
    return []

def save_picks_history(history):
    with open(PICKS_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def record_daily_picks(picks):
    """Save today's picks once per day, but only after 6:00 PM CT.
    Skips weekends since the market is closed."""
    from zoneinfo import ZoneInfo
    ct_now = datetime.now(ZoneInfo("America/Chicago"))

    # Skip weekends (Saturday=5, Sunday=6)
    if ct_now.weekday() >= 5:
        return

    # Only record after 6:00 PM CT
    if ct_now.hour < 18:
        return

    today = ct_now.strftime("%Y-%m-%d")
    history = load_picks_history()
    existing_dates = {e["date"] for e in history}
    if today in existing_dates:
        return

    for pick in picks:
        history.append({
            "date":          today,
            "sym":           pick["sym"],
            "name":          pick["name"],
            "price_at_pick": pick["price"],
        })
    save_picks_history(history)

if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

if "ticker_val" not in st.session_state:
    st.session_state.ticker_val = ""


# ── SEC EDGAR ─────────────────────────────────────────────────────────────────
EDGAR_HEADERS = {"User-Agent": "Bloomberg-Project research@bloomberg-project.com"}

@st.cache_data(ttl=3600)
def get_cik(ticker):
    r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=EDGAR_HEADERS, timeout=10)
    r.raise_for_status()
    for entry in r.json().values():
        if entry["ticker"].upper() == ticker.upper():
            return str(entry["cik_str"]).zfill(10)
    return None

@st.cache_data(ttl=3600)
def get_edgar_facts(cik):
    r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=EDGAR_HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=86400)
def get_company_list():
    """Returns list of (ticker, company_name) from SEC EDGAR, sorted by ticker."""
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=EDGAR_HEADERS, timeout=10)
        r.raise_for_status()
        entries = [(v["ticker"].upper(), v["title"].title()) for v in r.json().values()]
        return sorted(entries, key=lambda x: x[0])
    except Exception:
        return [
            ("AAPL","Apple Inc"),("MSFT","Microsoft Corp"),("NVDA","Nvidia Corp"),
            ("GOOGL","Alphabet Inc"),("AMZN","Amazon.com Inc"),("META","Meta Platforms"),
            ("TSLA","Tesla Inc"),("JPM","Jpmorgan Chase"),("BRK-B","Berkshire Hathaway"),
            ("XOM","Exxon Mobil"),("JNJ","Johnson & Johnson"),("V","Visa Inc"),
            ("UNH","Unitedhealth Group"),("WMT","Walmart Inc"),("PG","Procter & Gamble"),
            ("MA","Mastercard Inc"),("HD","Home Depot"),("CVX","Chevron Corp"),
            ("ABBV","Abbvie Inc"),("KO","Coca-Cola Co"),("PFE","Pfizer Inc"),
            ("BAC","Bank Of America"),("MRK","Merck & Co"),("LLY","Eli Lilly"),
            ("AVGO","Broadcom Inc"),("COST","Costco Wholesale"),("DIS","Walt Disney"),
            ("NFLX","Netflix Inc"),("AMD","Advanced Micro Devices"),("INTC","Intel Corp"),
        ]

EDGAR_INCOME = {
    "Revenue":              ["Revenues","RevenueFromContractWithCustomerExcludingAssessedTax","SalesRevenueNet","SalesRevenueGoodsNet"],
    "Cost of Revenue":      ["CostOfRevenue","CostOfGoodsAndServicesSold","CostOfGoodsSold"],
    "Gross Profit":         ["GrossProfit"],
    "R&D Expense":          ["ResearchAndDevelopmentExpense"],
    "SG&A Expense":         ["SellingGeneralAndAdministrativeExpense"],
    "Operating Expense":    ["OperatingExpenses"],
    "Operating Income":     ["OperatingIncomeLoss"],
    "Interest Expense":     ["InterestExpense","InterestAndDebtExpense","InterestExpenseDebt"],
    "Interest Income":      ["InterestAndDividendIncomeOperating","InvestmentIncomeInterest"],
    "Depreciation & Amort": ["DepreciationAndAmortization","Depreciation","DepreciationDepletionAndAmortization"],
    "Pretax Income":        ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
                             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
                             "IncomeLossBeforeIncomeTaxExpenseBenefit"],
    "Income Tax":           ["IncomeTaxExpenseBenefit","CurrentIncomeTaxExpenseBenefit"],
    "Net Income":           ["NetIncomeLoss","NetIncomeLossAvailableToCommonStockholdersBasic","ProfitLoss"],
    "EPS Basic":            ["EarningsPerShareBasic"],
    "EPS Diluted":          ["EarningsPerShareDiluted"],
    "Shares Outstanding":   ["CommonStockSharesOutstanding"],
}
EDGAR_BALANCE = {
    "Cash & Equivalents":     ["CashAndCashEquivalentsAtCarryingValue"],
    "Short-Term Investments":  ["ShortTermInvestments","MarketableSecuritiesCurrent"],
    "Accounts Receivable":     ["AccountsReceivableNetCurrent"],
    "Inventory":               ["InventoryNet"],
    "Total Current Assets":    ["AssetsCurrent"],
    "PP&E (net)":              ["PropertyPlantAndEquipmentNet"],
    "Goodwill":                ["Goodwill"],
    "Intangible Assets":       ["FiniteLivedIntangibleAssetsNet","IntangibleAssetsNetExcludingGoodwill"],
    "Total Assets":            ["Assets"],
    "Accounts Payable":        ["AccountsPayableCurrent"],
    "Short-Term Debt":         ["ShortTermBorrowings","DebtCurrent"],
    "Current Liabilities":     ["LiabilitiesCurrent"],
    "Long-Term Debt":          ["LongTermDebtNoncurrent","LongTermDebt"],
    "Total Liabilities":       ["Liabilities"],
    "Retained Earnings":       ["RetainedEarningsAccumulatedDeficit"],
    "Total Equity":            ["StockholdersEquity"],
}
EDGAR_CASHFLOW = {
    "Operating Cash Flow":  ["NetCashProvidedByUsedInOperatingActivities"],
    "Capital Expenditures": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "Free Cash Flow":       None,
    "Acquisitions":         ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "Investing Cash Flow":  ["NetCashProvidedByUsedInInvestingActivities"],
    "Dividends Paid":       ["PaymentsOfDividends","PaymentsOfDividendsCommonStock"],
    "Stock Buybacks":       ["PaymentsForRepurchaseOfCommonStock"],
    "Financing Cash Flow":  ["NetCashProvidedByUsedInFinancingActivities"],
}

SEARCH_KEYWORD_MAP = {
    "depreciation and amortization": "Depreciation & Amort",
    "depreciation & amortization":   "Depreciation & Amort",
    "depreciation":                  "Depreciation & Amort",
    "amortization":                  "Depreciation & Amort",
    "d&a":                           "Depreciation & Amort",
    "interest expense":              "Interest Expense",
    "interest income":               "Interest Income",
    "total revenue":                 "Revenue",
    "net revenue":                   "Revenue",
    "revenue":                       "Revenue",
    "sales":                         "Revenue",
    "net income":                    "Net Income",
    "net earnings":                  "Net Income",
    "net profit":                    "Net Income",
    "earnings":                      "Net Income",
    "gross profit":                  "Gross Profit",
    "operating income":              "Operating Income",
    "operating profit":              "Operating Income",
    "ebit":                          "Operating Income",
    "research and development":      "R&D Expense",
    "r&d":                           "R&D Expense",
    "research":                      "R&D Expense",
    "sga":                           "SG&A Expense",
    "selling general":               "SG&A Expense",
    "income tax":                    "Income Tax",
    "tax expense":                   "Income Tax",
    "earnings per share":            "EPS Diluted",
    "eps":                           "EPS Diluted",
    "pretax income":                 "Pretax Income",
    "pre tax income":                "Pretax Income",
    "pre-tax income":                "Pretax Income",
    "income before taxes":           "Pretax Income",
    "income before tax":             "Pretax Income",
    "earnings before tax":           "Pretax Income",
    "ebt":                           "Pretax Income",
    "profit before tax":             "Pretax Income",
    "free cash flow":                "Free Cash Flow",
    "fcf":                           "Free Cash Flow",
    "levered free cash flow":        "Free Cash Flow",
    "capital expenditure":           "Capital Expenditures",
    "capital expenditures":          "Capital Expenditures",
    "capex":                         "Capital Expenditures",
    "cap ex":                        "Capital Expenditures",
    "property plant and equipment":  "Capital Expenditures",
    "ppe purchases":                 "Capital Expenditures",
    "operating cash flow":           "Operating Cash Flow",
    "cash flow from operations":     "Operating Cash Flow",
    "cash from operations":          "Operating Cash Flow",
    "operating activities":          "Operating Cash Flow",
    "total assets":                  "Total Assets",
    "assets":                        "Total Assets",
    "long-term debt":                "Long-Term Debt",
    "long term debt":                "Long-Term Debt",
    "lt debt":                       "Long-Term Debt",
    "short-term debt":               "Short-Term Debt",
    "short term debt":               "Short-Term Debt",
    "current debt":                  "Short-Term Debt",
    "accounts receivable":           "Accounts Receivable",
    "receivables":                   "Accounts Receivable",
    "ar":                            "Accounts Receivable",
    "inventory":                     "Inventory",
    "inventories":                   "Inventory",
    "goodwill":                      "Goodwill",
    "intangibles":                   "Intangible Assets",
    "intangible assets":             "Intangible Assets",
    "retained earnings":             "Retained Earnings",
    "accumulated deficit":           "Retained Earnings",
    "stockholders equity":           "Total Equity",
    "shareholders equity":           "Total Equity",
    "total stockholders equity":     "Total Equity",
    "book value":                    "Total Equity",
    "equity":                        "Total Equity",
    "net assets":                    "Total Equity",
    "cash and equivalents":          "Cash & Equivalents",
    "cash equivalents":              "Cash & Equivalents",
    "cash and cash equivalents":     "Cash & Equivalents",
    "cash":                          "Cash & Equivalents",
    "buyback":                       "Stock Buybacks",
    "buybacks":                      "Stock Buybacks",
    "repurchase":                    "Stock Buybacks",
    "share repurchase":              "Stock Buybacks",
    "stock repurchase":              "Stock Buybacks",
    "dividends paid":                "Dividends Paid",
    "dividend":                      "Dividends Paid",
    "dividends":                     "Dividends Paid",
    "cost of revenue":               "Cost of Revenue",
    "cost of goods":                 "Cost of Revenue",
    "cost of goods sold":            "Cost of Revenue",
    "cogs":                          "Cost of Revenue",
    "cost of sales":                 "Cost of Revenue",
    "shares outstanding":            "Shares Outstanding",
    "shares":                        "Shares Outstanding",
    "diluted shares":                "Shares Outstanding",
    "gross margin":                  "Gross Profit",
    "total liabilities":             "Total Liabilities",
    "liabilities":                   "Total Liabilities",
    "total debt":                    "Total Debt",
    "total borrowings":              "Total Debt",
    "total financial debt":          "Total Debt",
    "current assets":                "Total Current Assets",
    "current liabilities":           "Current Liabilities",
    "current ratio":                 "Total Current Assets",
    "investing cash flow":           "Investing Cash Flow",
    "cash from investing":           "Investing Cash Flow",
    "financing cash flow":           "Financing Cash Flow",
    "cash from financing":           "Financing Cash Flow",
    "acquisitions":                  "Acquisitions",
    "pp&e":                          "PP&E (net)",
    "net ppe":                       "PP&E (net)",
    "fixed assets":                  "PP&E (net)",
    "operating expenses":            "Operating Expense",
    "opex":                          "Operating Expense",
    "ebitda":                        "EBITDA",
    "earnings before interest tax depreciation": "EBITDA",
    "ebit":                          "EBIT",
    "earnings before interest and tax": "EBIT",
    "earnings before interest":      "EBIT",
    "net debt":                      "Net Debt",
    "roe":                           "ROE %",
    "return on equity":              "ROE %",
    "roa":                           "ROA %",
    "return on assets":              "ROA %",
    "gross margin":                  "Gross Margin %",
    "gross margin percent":          "Gross Margin %",
    "operating margin":              "Operating Margin %",
    "operating margin percent":      "Operating Margin %",
    "net margin":                    "Net Margin %",
    "profit margin":                 "Net Margin %",
    "net profit margin":             "Net Margin %",
    "fcf margin":                    "FCF Margin %",
    "free cash flow margin":         "FCF Margin %",
    "debt to equity":                "Debt/Equity",
    "debt equity ratio":             "Debt/Equity",
    "d/e ratio":                     "Debt/Equity",
    "leverage ratio":                "Debt/Equity",
    "sg&a":                          "SG&A Expense",
    "selling general and administrative": "SG&A Expense",
}

def extract_edgar_annual(facts, concept_map):
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    rows = {}
    for label, gaap_names in concept_map.items():
        if gaap_names is None:
            continue
        for gname in gaap_names:
            node = us_gaap.get(gname)
            if not node:
                continue
            unit_vals = (node.get("units",{}).get("USD")
                         or node.get("units",{}).get("USD/shares")
                         or node.get("units",{}).get("shares") or [])
            annual = {}
            for rec in unit_vals:
                if rec.get("form") != "10-K":
                    continue
                fy, val = rec.get("fy"), rec.get("val")
                if fy and val is not None:
                    if fy not in annual or rec.get("frame","") > annual[fy].get("frame",""):
                        annual[fy] = rec
            if annual:
                rows[label] = {fy: d["val"] for fy, d in sorted(annual.items())}
                break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).T
    df.columns = [int(c) for c in df.columns]
    return df[sorted(df.columns, reverse=True)]

def resolve_company_ticker(query):
    """
    Given a company name or partial name (e.g. 'Pepsi', 'Goldman', 'Apple'),
    return (ticker, full_name) by matching against the SEC EDGAR company list.
    Returns None if no confident match found.
    """
    q = query.strip()
    if not q:
        return None
    q_up  = q.upper()
    q_low = q.lower()

    companies = get_company_list()

    # 1. Exact ticker match
    for sym, name in companies:
        if sym == q_up:
            return sym, name

    # 2. Exact company name match
    for sym, name in companies:
        if name.lower() == q_low:
            return sym, name

    # 3. Company name starts with query (≥3 chars)
    if len(q) >= 3:
        starts = [(sym, name) for sym, name in companies if name.lower().startswith(q_low)]
        if starts:
            # Prefer shorter (more specific) names
            starts.sort(key=lambda x: len(x[1]))
            return starts[0]

    # 4. Ticker starts with query
    ticker_starts = [(sym, name) for sym, name in companies if sym.startswith(q_up)]
    if ticker_starts:
        ticker_starts.sort(key=lambda x: len(x[0]))
        return ticker_starts[0]

    # 5. Query appears as a word inside the company name
    if len(q) >= 4:
        word_match = [(sym, name) for sym, name in companies
                      if re.search(r'\b' + re.escape(q_low) + r'\b', name.lower())]
        if word_match:
            word_match.sort(key=lambda x: len(x[1]))
            return word_match[0]

    # 6. Fuzzy match on company name
    if len(q) >= 4:
        names_lower = [name.lower() for _, name in companies]
        matches = get_close_matches(q_low, names_lower, n=1, cutoff=0.7)
        if matches:
            idx = names_lower.index(matches[0])
            return companies[idx]

    return None

# ── Common informal name → ticker overrides (handles nicknames) ───────────────
NAME_OVERRIDES = {
    "pepsi": "PEP", "pepsico": "PEP",
    "apple": "AAPL",
    "google": "GOOGL", "alphabet": "GOOGL",
    "facebook": "META",
    "amazon": "AMZN",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "nvidia": "NVDA", "nvdia": "NVDA",
    "meta": "META",
    "jpmorgan": "JPM", "jp morgan": "JPM", "chase": "JPM",
    "goldman": "GS", "goldman sachs": "GS",
    "berkshire": "BRK-B",
    "exxon": "XOM", "exxonmobil": "XOM",
    "walmart": "WMT",
    "johnson": "JNJ",
    "procter": "PG", "procter and gamble": "PG",
    "mastercard": "MA",
    "visa": "V",
    "home depot": "HD",
    "chevron": "CVX",
    "coca cola": "KO", "coke": "KO", "coca-cola": "KO",
    "pfizer": "PFE",
    "abbvie": "ABBV",
    "bank of america": "BAC",
    "merck": "MRK",
    "eli lilly": "LLY", "lilly": "LLY",
    "broadcom": "AVGO",
    "costco": "COST",
    "disney": "DIS", "walt disney": "DIS",
    "netflix": "NFLX",
    "amd": "AMD", "advanced micro": "AMD",
    "intel": "INTC",
    "salesforce": "CRM",
    "adobe": "ADBE",
    "oracle": "ORCL",
    "ibm": "IBM",
    "qualcomm": "QCOM",
    "uber": "UBER",
    "airbnb": "ABNB",
    "palantir": "PLTR",
    "snowflake": "SNOW",
    "servicenow": "NOW",
    "citigroup": "C", "citi": "C",
    "wells fargo": "WFC",
    "morgan stanley": "MS",
    "blackrock": "BLK",
    "boeing": "BA",
    "caterpillar": "CAT",
    "3m": "MMM",
    "general electric": "GE",
    "general motors": "GM",
    "ford": "F",
    "att": "T", "at&t": "T",
    "verizon": "VZ",
    "comcast": "CMCSA",
    "united health": "UNH", "unitedhealth": "UNH",
    "cvs": "CVS",
    "mcdonalds": "MCD", "mcdonald's": "MCD",
    "starbucks": "SBUX",
    "nike": "NKE",
    "target": "TGT",
    "paypal": "PYPL",
    "block": "SQ", "square": "SQ",
    "shopify": "SHOP",
    "spotify": "SPOT",
    "twitter": "X",
    "lyft": "LYFT",
    "doordash": "DASH",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "arm": "ARM",
    "astrazeneca": "AZN",
    "moderna": "MRNA",
    "biontech": "BNTX",
    "novartis": "NVS",
    "roche": "RHHBY",
    "shell": "SHEL",
    "bp": "BP",
    "volkswagen": "VWAGY",
    "toyota": "TM",
    "samsung": "SSNLF",
    "tsmc": "TSM",
    "alibaba": "BABA",
    "baidu": "BIDU",
    "tencent": "TCEHY",
}

def extract_ticker_from_question(question, provided_ticker=None):
    """
    Given a question and optional explicit ticker, return (ticker, company_name).
    Priority: provided_ticker box > uppercase token scan > override map > fuzzy name extraction.
    """
    companies = get_company_list()
    ticker_set = {sym for sym, _ in companies}

    # 1. Explicit ticker provided — resolve it (might be a name, not a ticker)
    if provided_ticker and provided_ticker.strip():
        t = provided_ticker.strip()
        override = NAME_OVERRIDES.get(t.lower())
        if override:
            name = next((n for s, n in companies if s == override), override)
            return override, name
        result = resolve_company_ticker(t)
        if result:
            return result
        return t.upper(), t.upper()

    q_low = question.lower()

    # 2. Scan original question for uppercase tokens that look like tickers (2-5 chars)
    #    e.g. "OXY pre tax income" → try "OXY" first
    tokens = re.findall(r'\b([A-Z]{2,5})\b', question)
    for tok in tokens:
        if tok in ticker_set:
            name = next((n for s, n in companies if s == tok), tok)
            return tok, name

    # 3. Check override map for known informal names inside the question
    for informal, sym in sorted(NAME_OVERRIDES.items(), key=lambda x: -len(x[0])):
        if informal in q_low:
            name = next((n for s, n in companies if s == sym), sym)
            return sym, name

    # 4. Strip all financial/metric words and years, try to resolve what's left
    financial_words = (
        r'\b(what|was|is|the|in|of|for|and|how|did|does|much|give|me|show|tell|report|'
        r'net|income|revenue|earnings|profit|expense|interest|depreciation|amortization|'
        r'cash|flow|operating|gross|margin|total|assets|debt|equity|eps|per|share|'
        r'dividend|yield|capital|expenditure|expenditures|free|fiscal|year|quarter|annual|'
        r'quarterly|sales|ebitda|ebit|gaap|adjusted|company|s|its|their|a|an|'
        r'pre|tax|taxes|before|after|pretax|capex|buyback|repurchase|inventory|'
        r'goodwill|receivable|receivables|payable|liabilities|equity|book|value|'
        r'price|ratio|multiple|growth|margin|return|rate|cost|goods|sold)\b'
    )
    core = re.sub(financial_words, ' ', q_low)
    core = re.sub(r'\b20\d{2}\b', '', core)
    core = re.sub(r"'s|'", '', core)
    core = re.sub(r'[^a-z\s]', ' ', core)
    core = re.sub(r'\s+', ' ', core).strip()

    if len(core) >= 2:
        result = resolve_company_ticker(core)
        if result:
            return result

    return None, None

def _resolve_label(q_lower, available_labels):
    """Return best matching label from available_labels, keyword map first then fuzzy.
    Returns None if no confident match — caller should surface a 'not found' message."""
    labels_lower = [l.lower() for l in available_labels]

    # 1. Keyword map — longest keyword wins to avoid partial matches
    for keyword in sorted(SEARCH_KEYWORD_MAP, key=len, reverse=True):
        if keyword in q_lower:
            target = SEARCH_KEYWORD_MAP[keyword]
            # Exact match in available labels
            if target in available_labels:
                return target
            # Case-insensitive match
            match = next((l for l in available_labels if l.lower() == target.lower()), None)
            if match:
                return match
            # Keyword matched but metric not available for this company — stop here,
            # don't fall through to fuzzy (avoids returning unrelated metrics)
            return None

    # 2. Strip noise words and try fuzzy — only with a high confidence cutoff
    filler = (r'\b(what|was|is|the|in|of|for|and|how|did|does|company|their|its|s|tell|'
              r'show|give|report|me|much|please|find|get|fetch|look|up)\b')
    core = re.sub(filler, ' ', q_lower)
    core = re.sub(r'\b[a-z]{1,4}\b', ' ', core)   # strip short tokens (tickers, filler)
    core = re.sub(r'\b20\d{2}\b', '', core)
    core = re.sub(r'[^a-z\s]', ' ', core)
    core = re.sub(r'\s+', ' ', core).strip()

    if len(core) >= 4:
        matches = get_close_matches(core, labels_lower, n=1, cutoff=0.6)
        if matches:
            return next((l for l in available_labels if l.lower() == matches[0]), None)

    return None

def _add_derived_metrics(df):
    """Compute derived financial metrics from raw EDGAR rows in-place."""
    def safe_row(label):
        if label in df.index:
            return df.loc[label].fillna(0)
        return pd.Series(0, index=df.columns)

    # EBITDA = Operating Income + D&A
    if "Operating Income" in df.index and "Depreciation & Amort" in df.index:
        df.loc["EBITDA"] = safe_row("Operating Income") + safe_row("Depreciation & Amort").abs()

    # EBIT = Operating Income (alias so keyword "ebit" resolves here too)
    if "Operating Income" in df.index:
        df.loc["EBIT"] = df.loc["Operating Income"]

    # Free Cash Flow
    if "Operating Cash Flow" in df.index and "Capital Expenditures" in df.index:
        df.loc["Free Cash Flow"] = safe_row("Operating Cash Flow") - safe_row("Capital Expenditures").abs()

    # Total Debt = LT Debt + ST Debt
    if "Long-Term Debt" in df.index or "Short-Term Debt" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        df.loc["Total Debt"] = total_debt

    # Net Debt = Total Debt - Cash
    if "Long-Term Debt" in df.index or "Short-Term Debt" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        df.loc["Net Debt"] = total_debt - safe_row("Cash & Equivalents")

    # ROE % = Net Income / Total Equity * 100
    if "Net Income" in df.index and "Total Equity" in df.index:
        eq = df.loc["Total Equity"].replace(0, float("nan"))
        df.loc["ROE %"] = df.loc["Net Income"] / eq * 100

    # ROA % = Net Income / Total Assets * 100
    if "Net Income" in df.index and "Total Assets" in df.index:
        ta = df.loc["Total Assets"].replace(0, float("nan"))
        df.loc["ROA %"] = df.loc["Net Income"] / ta * 100

    # Gross Margin %
    if "Gross Profit" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Gross Margin %"] = df.loc["Gross Profit"] / rev * 100

    # Operating Margin %
    if "Operating Income" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Operating Margin %"] = df.loc["Operating Income"] / rev * 100

    # Net Margin %
    if "Net Income" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Net Margin %"] = df.loc["Net Income"] / rev * 100

    # FCF Margin %
    if "Free Cash Flow" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["FCF Margin %"] = df.loc["Free Cash Flow"] / rev * 100

    # Debt / Equity
    if "Total Equity" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        eq = df.loc["Total Equity"].replace(0, float("nan"))
        df.loc["Debt/Equity"] = total_debt / eq

    return df

# Labels that are ratios/percentages — formatted differently in the answer box
RATIO_LABELS = {"ROE %","ROA %","Gross Margin %","Operating Margin %","Net Margin %",
                "FCF Margin %","Debt/Equity"}

def search_edgar(question, ticker):
    years = re.findall(r'\b(20\d{2})\b', question)
    target_year = int(years[0]) if years else None
    cik = get_cik(ticker)
    if not cik:
        return None
    facts = get_edgar_facts(cik)
    all_map = {**EDGAR_INCOME, **EDGAR_BALANCE, **{k: v for k,v in EDGAR_CASHFLOW.items() if v}}
    df = extract_edgar_annual(facts, all_map)
    if df.empty:
        return None
    df = _add_derived_metrics(df)
    best_label = _resolve_label(question.lower(), list(df.index))
    if not best_label:
        return None
    row = df.loc[best_label]
    available = [c for c in row.index if not (isinstance(row[c], float) and pd.isna(row[c]))]
    if not available:
        return None
    if target_year:
        if target_year in available:
            return row[target_year], best_label, target_year, "SEC EDGAR 10-K"
        closest = min(available, key=lambda y: abs(y - target_year))
        return row[closest], best_label, closest, f"SEC EDGAR 10-K (closest to {target_year})"
    yr = max(available)
    return row[yr], best_label, yr, "SEC EDGAR 10-K (most recent)"

def search_yfinance(question, stk):
    q = question.lower()
    years = re.findall(r'\b(20\d{2})\b', q)
    target_year = int(years[0]) if years else None
    index, all_items = {}, []
    for stmt_name, df in [("Income Statement", stk.financials), ("Balance Sheet", stk.balance_sheet), ("Cash Flow", stk.cashflow)]:
        if df is None or df.empty:
            continue
        for col in df.columns:
            try:
                col_dt = pd.to_datetime(col)
                period_str, period_year = col_dt.strftime("%Y-%m-%d"), col_dt.year
            except Exception:
                period_str, period_year = str(col), None
            for item, val in df[col].items():
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    continue
                index[(stmt_name, str(item), period_str, period_year)] = val
                if str(item) not in all_items:
                    all_items.append(str(item))
    if not index:
        return None
    best_item = _resolve_label(q, all_items)
    if not best_item:
        return None
    period_candidates = [(k,v) for k,v in index.items() if k[1] == best_item]
    if not period_candidates:
        return None
    if target_year:
        exact = [(k,v) for k,v in period_candidates if k[3] == target_year]
        period_candidates = exact or sorted(period_candidates, key=lambda x: abs((x[0][3] or 0) - target_year))
    else:
        period_candidates = sorted(period_candidates, key=lambda x: -(x[0][3] or 0))
    best_key, best_val = period_candidates[0]
    return best_val, best_key[1], best_key[2], best_key[0]

# ── Format helpers ─────────────────────────────────────────────────────────────
def fmt(val, prefix="", suffix="", decimals=2):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    return f"{prefix}{val:,.{decimals}f}{suffix}"

def fmt_large(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "N/A"
    if abs(val) >= 1e12: return f"${val/1e12:.2f}T"
    if abs(val) >= 1e9:  return f"${val/1e9:.2f}B"
    if abs(val) >= 1e6:  return f"${val/1e6:.2f}M"
    return f"${val:,.0f}"

def metric_card(label, value, css_class=""):
    if value == "N/A" or value is None:
        return
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value {css_class}">{value}</div>
    </div>""", unsafe_allow_html=True)

def render_fin_table(df):
    if df is None or df.empty:
        st.markdown("<p style='color:#64748b; padding:12px;'>Data not available.</p>", unsafe_allow_html=True)
        return
    cols = list(df.columns)
    hdrs = "".join(f"<th>{pd.to_datetime(c).strftime('%b %Y') if not isinstance(c,str) else c}</th>" for c in cols)
    rows = "".join(f"<tr><td>{lbl}</td>{''.join(f'<td>{fmt_large(row[c])}</td>' for c in cols)}</tr>" for lbl, row in df.iterrows())
    st.markdown(f'<div style="overflow-x:auto; background:#ffffff; border-radius:6px; border:1px solid #e2e8f0; padding:4px;"><table class="fin-table"><thead><tr><th>Line Item</th>{hdrs}</tr></thead><tbody>{rows}</tbody></table></div>', unsafe_allow_html=True)

def render_edgar_table(df):
    if df is None or df.empty:
        st.markdown("<p style='color:#64748b; padding:12px;'>Data not available from SEC EDGAR.</p>", unsafe_allow_html=True)
        return
    year_cols = sorted(df.columns, reverse=True)
    hdrs = "".join(f"<th>{y}</th>" for y in year_cols)
    rows_html = ""
    for label, row in df.iterrows():
        cells = "".join(
            f"<td style='color:#374151;'>—</td>" if (row.get(y) is None or (isinstance(row.get(y), float) and pd.isna(row.get(y))))
            else f"<td>{fmt_large(row[y]) if abs(row[y]) > 10000 else fmt(row[y])}</td>"
            for y in year_cols
        )
        rows_html += f"<tr><td>{label}</td>{cells}</tr>"
    st.markdown(f'<div style="overflow-x:auto; background:#ffffff; border-radius:6px; border:1px solid #e2e8f0; padding:4px;"><table class="fin-table"><thead><tr><th>Line Item</th>{hdrs}</tr></thead><tbody>{rows_html}</tbody></table></div>', unsafe_allow_html=True)

# ── Market data (no cache — refreshes with autorefresh) ───────────────────────
MARKET_TICKERS = [
    ("S&P 500", "^GSPC"), ("Dow",     "^DJI"),  ("Nasdaq",  "^IXIC"),
    ("Gold",    "GC=F"),  ("Oil",     "CL=F"),  ("Bitcoin", "BTC-USD"),
    ("10Y Yld", "^TNX"),  ("VIX",     "^VIX"),
]

@st.cache_data(ttl=15, show_spinner=False)
def get_market_data():
    results = []
    for name, sym in MARKET_TICKERS:
        try:
            fi = yf.Ticker(sym).fast_info
            price = getattr(fi, "last_price", None)
            prev  = getattr(fi, "previous_close", None)
            if price and prev:
                chg = price - prev
                pct = chg / prev * 100
                results.append((name, sym, price, chg, pct))
        except Exception:
            pass
    return results

@st.cache_data(ttl=1800, show_spinner=False)
def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        score  = int(d["value"])
        rating = d["value_classification"]
        return score, rating
    except Exception:
        return None, None

YIELD_CURVE_TICKERS = [("3M","^IRX"),("5Y","^FVX"),("10Y","^TNX"),("30Y","^TYX")]

@st.cache_data(ttl=900, show_spinner=False)
def get_yield_curve():
    points = []
    for label, sym in YIELD_CURVE_TICKERS:
        try:
            fi = yf.Ticker(sym).fast_info
            price = getattr(fi, "last_price", None)
            if price:
                points.append((label, round(price, 3)))
        except Exception:
            pass
    return points

@st.cache_data(ttl=900, show_spinner=False)
def get_market_news():
    seen, articles = set(), []
    for sym in ["SPY","AAPL","MSFT","NVDA","JPM"]:
        try:
            for a in (yf.Ticker(sym).news or [])[:6]:
                content = a.get("content", {})
                title = content.get("title") or a.get("title","")
                if not title or title in seen:
                    continue
                seen.add(title)
                url = ""
                cp = content.get("canonicalUrl",{})
                if isinstance(cp, dict): url = cp.get("url","")
                if not url:
                    ct = content.get("clickThroughUrl",{})
                    url = ct.get("url","") if isinstance(ct, dict) else ""
                if not url: url = a.get("link","")
                pub = content.get("pubDate") or a.get("providerPublishTime")
                try:
                    dt_str = datetime.fromtimestamp(pub).strftime("%b %d  %H:%M") if isinstance(pub,(int,float)) else pd.to_datetime(pub).strftime("%b %d  %H:%M")
                except Exception:
                    dt_str = ""
                provider = content.get("provider",{})
                source = provider.get("displayName","") if isinstance(provider,dict) else a.get("publisher","")
                articles.append({"title":title,"url":url,"source":source,"time":dt_str})
        except Exception:
            pass
    return articles[:18]

# ── Claude Picks ──────────────────────────────────────────────────────────────
CLAUDE_PICKS_POOL = [
    "NVDA","MSFT","AAPL","META","GOOGL","AMZN","TSLA","AMD","CRM","NOW",
    "AVGO","NFLX","UBER","PLTR","JPM","GS","V","MA","COST","LLY",
    "UNH","ABBV","XOM","CVX","CRWD",
]

@st.cache_data(ttl=900, show_spinner=False)
def get_claude_picks():
    candidates = []
    for sym in CLAUDE_PICKS_POOL:
        try:
            t    = yf.Ticker(sym)
            fi   = t.fast_info
            price = getattr(fi, "last_price", None) or 0
            prev  = getattr(fi, "previous_close", None) or price
            if not price or price < 5:
                continue
            pct_today = (price - prev) / prev * 100 if prev else 0
            volume    = getattr(fi, "three_month_average_volume", None)  # fast_info has this
            avg_vol   = getattr(fi, "three_month_average_volume", None) or 1
            # Use regular volume vs avg from fast_info
            day_vol   = getattr(fi, "last_volume", None) or 0
            vol_ratio = day_vol / avg_vol if avg_vol else 1
            w52_high  = getattr(fi, "year_high", None) or 0
            w52_low   = getattr(fi, "year_low",  None) or 0
            w52_range_pct = ((price - w52_low) / (w52_high - w52_low) * 100) if w52_high > w52_low else 50

            # Pull full info only for fundamentals (one call per stock, cached)
            info        = t.info
            fwd_pe      = info.get("forwardPE")
            trailing_pe = info.get("trailingPE")
            rev_growth  = info.get("revenueGrowth") or 0
            earn_growth = info.get("earningsGrowth") or 0
            profit_m    = info.get("profitMargins") or 0
            mean_target = info.get("targetMeanPrice") or 0
            analyst_up  = ((mean_target - price) / price * 100) if price and mean_target else 0
            market_cap  = info.get("marketCap") or 0
            name        = info.get("shortName") or sym
            sector      = info.get("sector", "")

            # Scoring — today's signals dominate so picks rotate daily
            score = 0
            score += (vol_ratio - 1) * 18 if vol_ratio > 1.2 else 0
            if 0.5 < pct_today < 8:
                score += pct_today * 6
            elif pct_today < -1:
                score -= abs(pct_today) * 3
            score += min(analyst_up, 30) * 0.8
            score += min(rev_growth * 100, 20) * 0.6
            score += min(earn_growth * 100, 20) * 0.6
            score += min(profit_m * 100, 15) * 0.3
            if w52_range_pct > 70:
                score += 4

            # Insight bullets
            bullets = []
            if analyst_up > 8:
                bullets.append(f"Analyst consensus: <b>${mean_target:.0f}</b> mean target — <b>+{analyst_up:.1f}%</b> upside from current price")
            if rev_growth > 0.10:
                bullets.append(f"Revenue growing <b>+{rev_growth*100:.0f}%</b> YoY — top-line momentum intact")
            if earn_growth > 0.10:
                bullets.append(f"Earnings growth of <b>+{earn_growth*100:.0f}%</b> YoY signals expanding profitability")
            if profit_m > 0.20:
                bullets.append(f"Strong net margin of <b>{profit_m*100:.1f}%</b> — high-quality earnings")
            if vol_ratio > 1.4:
                bullets.append(f"Trading at <b>{vol_ratio:.1f}×</b> average volume today — elevated institutional interest")
            if w52_range_pct > 75:
                bullets.append(f"Near <b>52-week high</b> ({w52_range_pct:.0f}th percentile of range) — strong uptrend")
            if fwd_pe and trailing_pe and fwd_pe < trailing_pe * 0.85:
                bullets.append(f"Forward P/E of <b>{fwd_pe:.1f}x</b> vs trailing <b>{trailing_pe:.1f}x</b> — earnings acceleration priced in")
            if not bullets:
                bullets.append(f"Quality franchise with market cap of <b>{fmt_large(market_cap)}</b> and consistent free cash flow generation")

            # Latest news headline
            news_headline, news_url, news_source, news_time = "", "", "", ""
            try:
                for a in (t.news or [])[:5]:
                    content = a.get("content", {})
                    title   = content.get("title") or a.get("title", "")
                    if not title:
                        continue
                    url = ""
                    cp = content.get("canonicalUrl", {})
                    if isinstance(cp, dict): url = cp.get("url", "")
                    if not url:
                        ct = content.get("clickThroughUrl", {})
                        url = ct.get("url", "") if isinstance(ct, dict) else ""
                    if not url: url = a.get("link", "")
                    pub = content.get("pubDate") or a.get("providerPublishTime")
                    try:
                        dt_str = datetime.fromtimestamp(pub).strftime("%b %d") if isinstance(pub, (int, float)) else pd.to_datetime(pub).strftime("%b %d")
                    except Exception:
                        dt_str = ""
                    provider = content.get("provider", {})
                    source   = provider.get("displayName", "") if isinstance(provider, dict) else a.get("publisher", "")
                    news_headline, news_url, news_source, news_time = title, url, source, dt_str
                    break
            except Exception:
                pass

            candidates.append({
                "sym": sym, "name": name, "price": price, "pct_today": pct_today,
                "analyst_up": analyst_up, "mean_target": mean_target,
                "rev_growth": rev_growth, "earn_growth": earn_growth,
                "score": score, "bullets": bullets[:3],
                "sector": sector, "fwd_pe": fwd_pe,
                "news_headline": news_headline, "news_url": news_url,
                "news_source": news_source, "news_time": news_time,
                "vol_ratio": vol_ratio,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: -x["score"])

    # Exclude stocks picked in the last 2 days so picks rotate
    history  = load_picks_history()
    cutoff   = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    recent   = {e["sym"] for e in history if e["date"] >= cutoff}

    seen_sectors, picks = set(), []
    for c in candidates:
        if len(picks) >= 3: break
        if c["sym"] in recent: continue
        if c["sector"] not in seen_sectors or len(picks) == 2:
            picks.append(c)
            seen_sectors.add(c["sector"])
    if len(picks) < 3:
        for c in candidates:
            if len(picks) >= 3: break
            if c not in picks:
                picks.append(c)
    return picks

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"], .main, .stApp {
        background-color: #ffffff;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .block-container { padding-top: 2.5rem !important; padding-bottom: 2rem; max-width: 1400px; }
    section[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
    header[data-testid="stHeader"] { background: #ffffff !important; border-bottom: 1px solid #e2e8f0; }
    header[data-testid="stHeader"] button { color: #0f172a !important; }
    header[data-testid="stHeader"] button:hover { color: #2563eb !important; background: #f0f7ff !important; }
    header[data-testid="stHeader"] a { color: #0f172a !important; }
    [data-testid="stToolbar"] button { color: #0f172a !important; }
    [data-testid="stToolbar"] svg { fill: #0f172a !important; color: #0f172a !important; }

    /* Hide the running spinner and overlay — updates feel instant */
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stAppViewBlockContainer"] > div[class*="withScreencast"] iframe { display: none !important; }
    div[data-testid="stDecoration"] { display: none !important; }

    .metric-card { background:#f8fafc; border:none; border-left:3px solid #e2e8f0; border-radius:0 4px 4px 0; padding:10px 14px; margin:3px 0; transition:border-left-color .15s, background .15s; }
    .metric-card:hover { border-left-color:#93c5fd; background:#f0f7ff; }
    .metric-label { color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:0.09em; font-weight:500; }
    .metric-value { color:#1e3a5c; font-size:18px; font-weight:600; margin-top:4px; font-family:'Inter',sans-serif; }
    .metric-value.positive { color:#16a34a; }
    .metric-value.negative { color:#dc2626; }

    .section-header {
        color:#94a3b8; font-size:10px; font-weight:600; text-transform:uppercase;
        letter-spacing:0.16em; border-bottom:1px solid #e2e8f0;
        padding:0 0 8px 2px; margin:28px 0 16px 0;
    }
    /* Period radio — pill style inside dialog */
    [data-testid="stDialog"] .stRadio > div { display:flex; gap:4px; flex-wrap:wrap; }
    [data-testid="stDialog"] .stRadio label,
    [data-testid="stDialog"] .stRadio label p,
    [data-testid="stDialog"] .stRadio label span {
        background:#f1f5f9 !important; border:1px solid #e2e8f0 !important;
        border-radius:20px !important; padding:3px 14px !important;
        font-size:12px !important; font-weight:600 !important;
        color:#1e293b !important; cursor:pointer !important; transition:all .15s !important;
    }
    [data-testid="stDialog"] .stRadio label:has(input:checked) {
        background:#1e3a5c !important; border-color:#1e3a5c !important; color:#ffffff !important;
    }
    [data-testid="stDialog"] .stRadio label:hover { border-color:#93c5fd !important; color:#2563eb !important; }

    .answer-box { background:#f0f7ff; border:1px solid #bfdbfe; border-left:3px solid #2563eb; border-radius:6px; padding:18px 22px; margin:10px 0; }
    .answer-label { color:#2563eb; font-size:10px; text-transform:uppercase; letter-spacing:0.1em; font-weight:600; }
    .answer-value { color:#1e3a5c; font-size:28px; font-weight:700; margin:6px 0 2px; font-family:'Inter',sans-serif; }
    .answer-item  { color:#64748b; font-size:13px; font-weight:500; }
    .answer-meta  { color:#94a3b8; font-size:12px; margin-top:4px; }

    .news-card { background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:11px 15px; margin-bottom:6px; transition:border-color .15s; }
    .news-card:hover { border-color:#93c5fd; }
    .news-title a { color:#2d4a6a !important; text-decoration:none !important; font-size:12.5px; font-weight:500; line-height:1.5; display:block; }
    .news-title a:hover { color:#2563eb !important; }
    .news-meta { color:#94a3b8; font-size:10.5px; margin-top:4px; }

    .fin-table { width:100%; border-collapse:collapse; font-size:12px; font-family:'Inter',sans-serif; }
    .fin-table th { background:#f1f5f9; color:#94a3b8; padding:9px 12px; text-align:right; font-weight:600; font-size:10px; text-transform:uppercase; letter-spacing:0.08em; border-bottom:1px solid #e2e8f0; }
    .fin-table th:first-child { text-align:left; min-width:190px; }
    .fin-table td { padding:7px 12px; color:#94a3b8; border-bottom:1px solid #f1f5f9; text-align:right; }
    .fin-table td:first-child { color:#64748b; text-align:left; }
    .fin-table tr:hover td { background:#f8fafc; }

    .co-header { background:#f8fafc; border:none; border-bottom:2px solid #e2e8f0; border-radius:8px; padding:22px 28px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,0.04); }

    div.mover-btn > div > button {
        background:#f8fafc !important; border:1px solid #e2e8f0 !important;
        border-radius:5px !important; padding:6px 10px !important;
        width:100% !important; text-align:left !important;
        font-size:12.5px !important; color:#2d4a6a !important;
        margin-bottom:4px !important; min-height:0 !important; height:36px !important;
        font-family:'Inter',sans-serif !important;
    }
    div.mover-btn > div > button:hover { background:#eff6ff !important; border-color:#93c5fd !important; }

    .beat   { color:#16a34a; font-weight:600; }
    .miss   { color:#dc2626; font-weight:600; }
    .inline { color:#64748b; font-weight:600; }

    h1,h2,h3 { color:#1e3a5c !important; font-family:'Inter',sans-serif !important; }
    .stTextInput > div > div > input {
        background-color:#ffffff !important; color:#1e3a5c !important;
        border:1.5px solid #cbd5e1 !important; font-size:14px;
        border-radius:5px; font-family:'Inter',sans-serif !important;
    }
    .stTextInput > div > div > input:focus {
        border-color:#2563eb !important;
        box-shadow: 0 0 0 3px rgba(37,99,235,0.1) !important;
    }
    .stTextInput > div > div > input::placeholder { color:#94a3b8 !important; }
    div[data-testid="stTabs"] button { color:#94a3b8 !important; font-family:'Inter',sans-serif !important; font-size:13px !important; }
    div[data-testid="stTabs"] button[aria-selected="true"] { color:#1e3a5c !important; border-bottom-color:#2563eb !important; }
    .stRadio label { color:#475569 !important; font-size:13px !important; font-family:'Inter',sans-serif !important; }
    .stForm { border:none !important; padding:0 !important; }
    button[kind="formSubmit"] {
        background:#ffffff !important; border:1.5px solid #cbd5e1 !important;
        color:#1e3a5c !important; font-family:'Inter',sans-serif !important;
        font-size:13px !important; font-weight:500 !important; border-radius:5px !important;
    }
    button[kind="formSubmit"]:hover { background:#eff6ff !important; border-color:#2563eb !important; color:#2563eb !important; }

    /* All dialogs — white background */
    [data-testid="stDialog"] > div,
    [data-testid="stDialog"] [data-testid="stVerticalBlock"] {
        background-color: #ffffff !important;
    }
    [data-testid="stDialog"] { background: rgba(30,58,92,0.18) !important; }

    /* Sidebar remove buttons — small and tight */
    section[data-testid="stSidebar"] button {
        color: #94a3b8 !important;
        background: transparent !important;
        border: none !important;
        border-radius: 3px !important;
        padding: 0 4px !important;
        min-height: 0 !important;
        height: 20px !important;
        font-size: 11px !important;
        line-height: 1 !important;
    }
    section[data-testid="stSidebar"] button:hover {
        color: #ef4444 !important;
        background: #fef2f2 !important;
    }
    section[data-testid="stSidebar"] button p {
        font-size: 11px !important;
        line-height: 1 !important;
    }

    /* Gainers / losers label text */
    .mover-label-g { color: #16a34a; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; margin-bottom:6px; }
    .mover-label-l { color: #dc2626; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; margin-bottom:6px; }

    /* All regular buttons */
    button[kind="secondary"] {
        color: #3d5a7a !important;
        background: #f8fafc !important;
        border: 1px solid #dde6f0 !important;
        font-family: 'Inter', sans-serif !important;
    }
    button[kind="secondary"]:hover {
        color: #2563eb !important;
        background: #eff6ff !important;
        border-color: #93c5fd !important;
    }
</style>
""", unsafe_allow_html=True)

# ── Sidebar: Watchlist ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("<p style='color:#5a7a99; font-size:10px; font-weight:600; letter-spacing:0.16em; text-transform:uppercase; font-family:Inter,sans-serif;'>Watchlist</p>", unsafe_allow_html=True)
    st.markdown("<p style='color:#94a3b8; font-size:11px; margin:-4px 0 10px;'>Add stocks via the company profile.</p>", unsafe_allow_html=True)

    @st.fragment(run_every=15)
    def render_watchlist():
        remove_target = None
        for sym in st.session_state.watchlist:
            try:
                fi = yf.Ticker(sym).fast_info
                price = getattr(fi, "last_price", None)
                prev  = getattr(fi, "previous_close", None)
                if price and prev:
                    chg = price - prev; pct = chg / prev * 100
                    color = "#22c55e" if chg >= 0 else "#ef4444"
                    arrow = "▲" if chg >= 0 else "▼"
                    sign  = "+" if chg >= 0 else ""
                    p_str = f"${price:,.2f}"
                    c_str = f"{arrow} {sign}{pct:.2f}%"
                else:
                    color, p_str, c_str = "#64748b", "N/A", ""
            except Exception:
                color, p_str, c_str = "#64748b", "N/A", ""
            info_col, btn_col = st.columns([5, 1])
            with info_col:
                st.markdown(
                    f'<div style="padding:5px 0;border-bottom:1px solid #e2e8f0;">'
                    f'<span style="color:#1e3a5c;font-weight:600;font-size:14px;">{sym}</span><br>'
                    f'<span style="color:#64748b;font-size:13px;">{p_str}</span>'
                    f'<span style="color:{color};font-size:12px;margin-left:6px;">{c_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with btn_col:
                st.markdown('<div style="margin-top:6px;">', unsafe_allow_html=True)
                if st.button("✕", key=f"rm_{sym}"):
                    remove_target = sym
                st.markdown('</div>', unsafe_allow_html=True)
        if remove_target:
            st.session_state.watchlist.remove(remove_target)
            save_watchlist(st.session_state.watchlist)
            st.rerun()
        if not st.session_state.watchlist:
            st.markdown("<p style='color:#64748b;font-size:13px;margin-top:8px;'>No tickers added yet.</p>", unsafe_allow_html=True)

    render_watchlist()

# ══════════════════════════════════════════════════════════════════════════════
# Pre-warm company list so it's cached before user types
if "companies_loaded" not in st.session_state:
    get_company_list()
    st.session_state.companies_loaded = True

# ══════════════════════════════════════════════════════════════════════════════
# HEADER + MARKET STRIP  (fragment = silent background refresh, no full-page flash)
# ══════════════════════════════════════════════════════════════════════════════
import streamlit.components.v1 as components

st.markdown(f"""
<div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0 6px;">
    <div>
        <span style="color:#1e3a5c; font-size:24px; font-weight:800; letter-spacing:-0.5px;">Mini Bloomberg</span>
        <span style="color:#94a3b8; font-size:13px; margin-left:12px;">Financial Terminal</span>
    </div>
    <div style="color:#94a3b8; font-size:12px;" id="live-clock"></div>
</div>
""", unsafe_allow_html=True)

# Zero-height iframe that drives the live clock every second via JS
components.html("""
<script>
function updateClock() {
    var el = window.parent.document.getElementById('live-clock');
    if (!el) return;
    var now = new Date();
    var days   = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var day  = days[now.getDay()];
    var mon  = months[now.getMonth()];
    var date = now.getDate();
    var yr   = now.getFullYear();
    var h    = String(now.getHours()).padStart(2,'0');
    var m    = String(now.getMinutes()).padStart(2,'0');
    var s    = String(now.getSeconds()).padStart(2,'0');
    el.textContent = day + ' ' + mon + ' ' + date + ', ' + yr + '    ' + h + ':' + m + ':' + s;
}
updateClock();
setInterval(updateClock, 1000);
</script>
""", height=0, scrolling=False)

@st.fragment(run_every=15)
def render_market_strip():
    market_data = get_market_data()

    if market_data:
        chip_divs = ""
        for name, sym, price, chg, pct in market_data:
            sign      = "+" if chg >= 0 else ""
            arrow     = "▲" if chg >= 0 else "▼"
            clr       = "#22c55e" if chg >= 0 else "#ef4444"
            price_str = f"{price:.2f}" if sym in ("^TNX","^VIX") else (f"{price:,.0f}" if price >= 1000 else f"{price:,.2f}")
            chip_divs += f"""
            <div class="chip" onclick="clickChip('{sym}')"
                 onmouseover="this.style.borderColor='#2563eb';this.style.background='#eff6ff'"
                 onmouseout="this.style.borderColor='#e2e8f0';this.style.background='#ffffff'">
                <div class="chip-name">{name}</div>
                <div class="chip-price">{price_str}</div>
                <div class="chip-chg" style="color:{clr};">{arrow} {sign}{pct:.2f}%</div>
            </div>"""

        components.html(f"""
        <style>
            body {{ margin:0; background:transparent; font-family:-apple-system,sans-serif; color:#1e3a5c; }}
            .strip {{ display:flex; gap:8px; height:88px; }}
            .chip {{
                flex:1; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px;
                display:flex; flex-direction:column; align-items:center; justify-content:center;
                gap:4px; cursor:pointer; transition:border-color .15s, background .15s;
                user-select:none;
            }}
            .chip-name  {{ color:#94a3b8; font-size:10px; text-transform:uppercase; letter-spacing:.06em; font-weight:600; }}
            .chip-price {{ color:#1e3a5c; font-size:15px; font-weight:700; }}
            .chip-chg   {{ font-size:12px; font-weight:700; }}
        </style>
        <div class="strip">{chip_divs}</div>
        <script>
        function clickChip(sym) {{
            const label = 'CHIP.TRIGGER.' + sym;
            const buttons = window.parent.document.querySelectorAll('button');
            for (const btn of buttons) {{
                if (btn.textContent.trim() === label) {{
                    btn.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
                    return;
                }}
            }}
        }}
        </script>
        """, height=92, scrolling=False)

render_market_strip()

st.markdown("<hr style='border-color:#e2e8f0; margin:4px 0 16px;'>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TWO-COLUMN LAYOUT
# ══════════════════════════════════════════════════════════════════════════════
left_col, right_col = st.columns([3,2], gap="large")

with left_col:

    # ── Financial Search ───────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Financial Data Search</div>', unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b; font-size:12px; margin:-8px 0 12px;'>Ask any question about a company's financials. Data goes back to early 2000s via SEC EDGAR.</p>", unsafe_allow_html=True)

    with st.form("financial_search_form"):
        ai_question = st.text_input("Financial question", placeholder='e.g. "AAPL net income 2023" or "What was Microsoft\'s depreciation in 2016?"', label_visibility="collapsed")
        search_btn = st.form_submit_button("Search", use_container_width=True)

    st.markdown("<p style='color:#94a3b8; font-size:11px; margin-top:4px;'>Try: &nbsp; MSFT depreciation 2016 &nbsp;·&nbsp; AAPL interest expense 2019 &nbsp;·&nbsp; OXY pretax income 2023 &nbsp;·&nbsp; NVDA EBITDA 2022</p>", unsafe_allow_html=True)

    if ai_question and search_btn:
        search_ticker, s_name = extract_ticker_from_question(ai_question, None)

        if not search_ticker:
            st.info("Couldn't identify the company. Include the ticker or company name in your question — e.g. 'AAPL revenue 2023' or 'Apple net income 2022'.")
        else:
            with st.spinner(f"Searching {s_name or search_ticker}…"):
                try:
                    # Confirm name from yfinance if we don't have it
                    if not s_name or s_name == search_ticker:
                        try:
                            info = yf.Ticker(search_ticker).info
                            s_name = info.get("longName") or info.get("shortName") or search_ticker
                        except Exception:
                            s_name = search_ticker

                    result = None
                    try:
                        result = search_edgar(ai_question, search_ticker)
                    except Exception:
                        pass
                    if not result:
                        try:
                            result = search_yfinance(ai_question, yf.Ticker(search_ticker))
                        except Exception:
                            pass
                    if result:
                        val, item, period, source = result
                        try:
                            period_label = f"Fiscal Year {period}" if isinstance(period, int) else pd.to_datetime(str(period)).strftime("%b %d, %Y")
                        except Exception:
                            period_label = str(period)
                        if item in RATIO_LABELS:
                            if "%" in item:
                                fv = f"{val:.2f}%"
                            else:
                                fv = f"{val:.2f}x"
                        elif isinstance(val, (int, float)) and abs(val) > 10000:
                            fv = fmt_large(val)
                        else:
                            fv = fmt(val)
                        st.markdown(f"""
                        <div class="answer-box">
                            <div class="answer-label">{s_name} ({search_ticker}) · {source}</div>
                            <div class="answer-item">{item}</div>
                            <div class="answer-value">{fv}</div>
                            <div class="answer-meta">{period_label}</div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div style="background:#0d1f35;border:1px solid #374151;border-radius:10px;padding:16px 20px;margin:10px 0;">
                            <div style="color:#c8a84b;font-size:13px;font-weight:600;">Metric not found for {s_name} ({search_ticker})</div>
                            <div style="color:#64748b;font-size:12px;margin-top:6px;">
                                This metric may not be reported by this company, or try rephrasing.<br>
                                <span style="color:#64748b;">Examples that work: &nbsp;
                                <b style="color:#94a3b8;">revenue · net income · EBITDA · free cash flow · total debt · net debt · ROE · gross margin · pretax income · capex</b>
                                </span>
                            </div>
                        </div>""", unsafe_allow_html=True)
                except Exception as e:
                    st.error(f"Error: {e}")

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    # ── Company Profile Lookup ─────────────────────────────────────────────────
    st.markdown('<div class="section-header">Company Profile Lookup</div>', unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b; font-size:12px; margin:-8px 0 12px;'>Search by company name or ticker. Press Enter or click Search to see results.</p>", unsafe_allow_html=True)

    with st.form("company_search_form"):
        company_query = st.text_input(
            "Company search",
            placeholder="Type a company name or ticker  (e.g.  Apple,  MSFT,  Nvidia…)",
            label_visibility="collapsed",
            key="company_query",
        )
        company_search_btn = st.form_submit_button("Search", use_container_width=True)

    # On submit, compute results and store in session state
    if company_search_btn and company_query:
        companies = get_company_list()
        q_up  = company_query.strip().upper()
        q_low = company_query.strip().lower()
        scored = []
        for sym, name in companies:
            name_l = name.lower()
            if sym == q_up:                        scored.append((0, len(name), name, sym))
            elif name_l == q_low:                  scored.append((1, len(name), name, sym))
            elif name_l.startswith(q_low):         scored.append((2, len(name), name, sym))
            elif sym.startswith(q_up):             scored.append((3, len(sym),  name, sym))
            elif q_low in name_l:                  scored.append((4, len(name), name, sym))
        scored.sort(key=lambda x: (x[0], x[1]))
        if len(scored) == 1:
            st.session_state["open_ticker"] = scored[0][3]
            st.session_state["company_results"] = []
            st.rerun()
        else:
            st.session_state["company_results"] = scored[:8]

    # Render results from session state so buttons stay alive for Streamlit to process clicks
    results = st.session_state.get("company_results", [])
    if results:
        for _, _, name, sym in results:
            display = f"**{sym}** &nbsp; {name[:50]}{'…' if len(name)>50 else ''}"
            if st.button(display, key=f"suggest_{sym}", width="stretch"):
                st.session_state["company_results"] = []
                st.session_state["open_ticker"] = sym
                st.rerun()
    elif company_search_btn and company_query:
        st.markdown("<p style='color:#64748b; font-size:12px; margin-top:6px;'>No matches found.</p>", unsafe_allow_html=True)

    # ── Sector Performance ─────────────────────────────────────────────────────
    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Sector Performance</div>', unsafe_allow_html=True)

    SECTORS = [
        ("Technology",    "XLK"), ("Financials",   "XLF"), ("Healthcare",    "XLV"),
        ("Energy",        "XLE"), ("Industrials",  "XLI"), ("Consumer Disc", "XLY"),
        ("Consumer Stap", "XLP"), ("Utilities",    "XLU"), ("Real Estate",   "XLRE"),
        ("Materials",     "XLB"), ("Communication","XLC"),
    ]

    @st.cache_data(ttl=300, show_spinner=False)
    def get_sector_data():
        results = []
        for name, sym in SECTORS:
            try:
                fi = yf.Ticker(sym).fast_info
                price = getattr(fi, "last_price", None)
                prev  = getattr(fi, "previous_close", None)
                if price and prev:
                    pct = (price - prev) / prev * 100
                    results.append((name, sym, pct))
            except Exception:
                pass
        return sorted(results, key=lambda x: -x[2])

    sector_data = get_sector_data()
    if sector_data:
        max_abs = max(abs(pct) for _, _, pct in sector_data) or 1
        rows_html = ""
        for name, sym, pct in sector_data:
            sign      = "+" if pct >= 0 else ""
            color     = "#22c55e" if pct >= 0 else "#ef4444"
            bar_w     = int(abs(pct) / max_abs * 100)
            bar_color = "#166534" if pct >= 0 else "#7f1d1d"
            rows_html += f"""
            <div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f1f5f9;">
                <div style="width:116px;color:#64748b;font-size:12px;flex-shrink:0;">{name}</div>
                <div style="flex:1;background:#e2e8f0;border-radius:3px;height:6px;overflow:hidden;">
                    <div style="width:{bar_w}%;background:{bar_color};height:100%;border-radius:3px;"></div>
                </div>
                <div style="width:60px;text-align:right;color:{color};font-size:12px;font-weight:700;">{sign}{pct:.2f}%</div>
                <div style="width:40px;text-align:right;color:#94a3b8;font-size:11px;">{sym}</div>
            </div>"""
        st.markdown(rows_html, unsafe_allow_html=True)

    # ── Top Movers ─────────────────────────────────────────────────────────────
    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Top Movers</div>', unsafe_allow_html=True)
    st.markdown("""
    """, unsafe_allow_html=True)

    @st.cache_data(ttl=30, show_spinner=False)
    def get_top_movers():
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        gainers, losers = [], []
        for scr_id, lst in [("day_gainers", gainers), ("day_losers", losers)]:
            try:
                url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=true&scrIds={scr_id}&count=25"
                r = requests.get(url, headers=headers, timeout=10)
                quotes = r.json()["finance"]["result"][0]["quotes"]
                for q in quotes:
                    sym   = q.get("symbol", "")
                    price = (q.get("regularMarketPrice") or {}).get("raw", 0)
                    pct   = (q.get("regularMarketChangePercent") or {}).get("raw", 0)
                    if price >= 5 and sym and "." not in sym and len(sym) <= 5:
                        lst.append((sym, price, pct))
            except Exception:
                pass
        return gainers[:6], losers[:6]

    @st.fragment(run_every=30)
    def render_top_movers():
        gainers, losers = get_top_movers()

        def build_rows(items, is_gainer):
            html = ""
            for sym, price, pct in items:
                sign  = "+" if pct >= 0 else ""
                arrow = "▲" if pct >= 0 else "▼"
                if is_gainer:
                    bg, border, txt, chg_clr = "#f0fdf4", "#bbf7d0", "#166534", "#16a34a"
                else:
                    bg, border, txt, chg_clr = "#fef2f2", "#fecaca", "#991b1b", "#dc2626"
                html += (
                    f'<div class="mrow" onclick="clickMover(\'{sym}\')"'
                    f' style="background:{bg};border:1px solid {border};border-radius:6px;'
                    f'padding:11px 14px;margin-bottom:8px;display:flex;justify-content:space-between;'
                    f'align-items:center;cursor:pointer;">'
                    f'<span style="color:{txt};font-weight:700;font-size:13px;">{sym}</span>'
                    f'<span style="color:#475569;font-size:12.5px;">${price:,.2f}</span>'
                    f'<span style="color:{chg_clr};font-weight:700;font-size:12.5px;">{arrow} {sign}{pct:.2f}%</span>'
                    f'</div>'
                )
            return html

        g_rows   = build_rows(gainers, True)
        l_rows   = build_rows(losers, False)
        iframe_h = max(len(gainers), len(losers)) * 58 + 36

        components.html(f"""
        <style>
          body {{ margin:0; padding:0; background:transparent; font-family:-apple-system,'Inter',sans-serif; }}
          .col-label {{ font-size:11px; font-weight:700; text-transform:uppercase;
                        letter-spacing:.08em; margin-bottom:7px; }}
          .label-g {{ color:#16a34a; }} .label-l {{ color:#dc2626; }}
          .mrow:hover {{ opacity:0.82; }}
        </style>
        <div style="display:flex;gap:12px;">
          <div style="flex:1;"><div class="col-label label-g">Top Gainers</div>{g_rows}</div>
          <div style="flex:1;"><div class="col-label label-l">Top Losers</div>{l_rows}</div>
        </div>
        <script>
        function clickMover(sym) {{
          const buttons = window.parent.document.querySelectorAll('button');
          for (const btn of buttons) {{
            if (btn.innerText.trim() === 'MOVER.' + sym) {{ btn.click(); return; }}
          }}
        }}
        </script>
        """, height=iframe_h, scrolling=False)

    render_top_movers()

    # ── Claude Picks ───────────────────────────────────────────────────────────
    st.markdown('<div style="margin-top:-18px;"><div class="section-header">Claude Picks — Market Close Outlook</div></div>', unsafe_allow_html=True)
    st.markdown("<p style='color:#64748b; font-size:12px; margin:-8px 0 14px;'>Stocks with strong fundamentals and potential catalysts for tomorrow's session.</p>", unsafe_allow_html=True)

    picks = get_claude_picks()

    # Persist today's picks once per day for the performance tracker
    if picks:
        record_daily_picks(picks)

    if picks:
        for i, pick in enumerate(picks):
            sym        = pick["sym"]
            name       = pick["name"]
            price      = pick["price"]
            pct        = pick["pct_today"]
            analyst_up = pick["analyst_up"]
            bullets    = pick["bullets"]
            sector     = pick["sector"]
            fwd_pe     = pick["fwd_pe"]
            news_h     = pick["news_headline"]
            news_url   = pick["news_url"]
            news_src   = pick["news_source"]
            news_t     = pick["news_time"]
            vol_ratio  = pick["vol_ratio"]

            sign      = "+" if pct >= 0 else ""
            pct_color = "#22c55e" if pct >= 0 else "#ef4444"
            up_sign   = "+" if analyst_up >= 0 else ""

            # Build all HTML fragments first — no nested f-strings inside st.markdown
            bullets_html = "".join(
                '<div style="display:flex;gap:8px;align-items:flex-start;margin-bottom:7px;">'
                '<span style="color:#2563eb;font-size:14px;margin-top:-1px;flex-shrink:0;">&#8250;</span>'
                '<span style="color:#475569;font-size:12.5px;line-height:1.5;">' + b + '</span>'
                '</div>'
                for b in bullets
            )

            fwd_pe_badge = (
                '<span style="background:#eff6ff;color:#2563eb;font-size:10px;font-weight:600;'
                'padding:2px 8px;border-radius:10px;margin-left:6px;">Fwd P/E ' + f'{fwd_pe:.1f}' + 'x</span>'
            ) if fwd_pe else ""

            sector_tag = (
                '<span style="background:#f1f5f9;color:#64748b;font-size:10px;font-weight:600;'
                'padding:2px 9px;border-radius:10px;">' + sector + '</span>'
            ) if sector else ""

            upside_tag = (
                '<span style="background:#f0fdf4;color:#16a34a;font-size:10px;font-weight:600;'
                'padding:2px 9px;border-radius:10px;">' + up_sign + f'{analyst_up:.1f}' + '% analyst upside</span>'
            ) if abs(analyst_up) > 1 else ""

            vol_tag = (
                '<span style="background:#fff7ed;color:#ea580c;font-size:10px;font-weight:600;'
                'padding:2px 9px;border-radius:10px;">' + f'{vol_ratio:.1f}' + '&#215; avg volume</span>'
            ) if vol_ratio > 1.3 else ""

            tags_html = sector_tag + ("&nbsp;" if sector_tag and (upside_tag or vol_tag) else "") + upside_tag + ("&nbsp;" if upside_tag and vol_tag else "") + vol_tag

            news_block = ""
            if news_h:
                sep = "&nbsp;&#183;&nbsp;" if news_src and news_t else ""
                if news_url:
                    link_open  = '<a href="' + news_url + '" target="_blank" style="color:#2563eb;text-decoration:none;">'
                    link_close = '</a>'
                else:
                    link_open, link_close = '<span style="color:#475569;">', '</span>'
                news_block = (
                    '<div style="background:#f8fafc;border-left:3px solid #93c5fd;border-radius:0 5px 5px 0;'
                    'padding:8px 12px;margin-top:10px;">'
                    '<div style="color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">Latest News</div>'
                    + link_open +
                    '<span style="font-size:12px;font-weight:500;line-height:1.5;">' + news_h + '</span>'
                    + link_close +
                    '<div style="color:#94a3b8;font-size:10.5px;margin-top:3px;">' + news_src + sep + news_t + '</div>'
                    '</div>'
                )

            card_html = (
                '<div style="background:#ffffff;border:1.5px solid #e2e8f0;border-radius:10px;'
                'padding:18px 22px;margin-bottom:14px;box-shadow:0 1px 4px rgba(30,58,92,0.06);">'

                '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
                '<div>'
                '<span style="color:#1e3a5c;font-size:17px;font-weight:800;letter-spacing:-0.3px;">' + sym + '</span>'
                '<span style="color:#64748b;font-size:13px;margin-left:8px;">' + name + '</span>'
                + fwd_pe_badge +
                '</div>'
                '<div style="text-align:right;">'
                '<div style="color:#1e3a5c;font-size:17px;font-weight:700;">$' + f'{price:,.2f}' + '</div>'
                '<div style="color:' + pct_color + ';font-size:12px;font-weight:600;">' + sign + f'{pct:.2f}' + '% today</div>'
                '</div>'
                '</div>'

                '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">'
                + tags_html +
                '</div>'

                '<div style="margin-bottom:4px;">'
                + bullets_html +
                '</div>'

                + news_block +
                '</div>'
            )

            st.markdown(card_html, unsafe_allow_html=True)

            cp_col1, cp_col2 = st.columns([5, 1])
            with cp_col2:
                if st.button("View →", key=f"cpick_{sym}_{i}", width="stretch"):
                    st.session_state["open_ticker"] = sym
                    st.rerun()
    else:
        st.markdown("<p style='color:#94a3b8;font-size:13px;'>Picks unavailable — market data loading.</p>", unsafe_allow_html=True)

with right_col:
    # ── Market Headlines ───────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Market Headlines</div>', unsafe_allow_html=True)
    headlines = get_market_news()
    if headlines:
        for h in headlines:
            if h["url"]:
                title_html = f'<a href="{h["url"]}" target="_blank">{h["title"]}</a>'
            else:
                title_html = h["title"]
            meta = f'{h["source"]}{"&nbsp;·&nbsp;" if h["source"] and h["time"] else ""}{h["time"]}'
            st.markdown(f"""
            <div class="news-card">
                <div class="news-title">{title_html}</div>
                <div class="news-meta">{meta}</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("<p style='color:#94a3b8;'>No headlines available right now.</p>", unsafe_allow_html=True)

    # ── Fear & Greed Index ─────────────────────────────────────────────────────
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Fear &amp; Greed Index</div>', unsafe_allow_html=True)
    fg_score, fg_rating = get_fear_greed()
    if fg_score is not None:
        if fg_score >= 75:   fg_color, fg_emoji = "#2db87d", ""
        elif fg_score >= 55: fg_color, fg_emoji = "#5ac996", ""
        elif fg_score >= 45: fg_color, fg_emoji = "#c8a84b", ""
        elif fg_score >= 25: fg_color, fg_emoji = "#d4784a", ""
        else:                fg_color, fg_emoji = "#e05252", ""
        bar_w = fg_score
        html = (
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px 20px;">'
            f'<div style="margin-bottom:10px;"><span style="color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;">Market Sentiment</span></div>'
            f'<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px;">'
            f'<span style="color:{fg_color};font-size:44px;font-weight:800;line-height:1;">{fg_score}</span>'
            f'<span style="color:{fg_color};font-size:14px;font-weight:600;">{fg_rating}</span>'
            f'</div>'
            f'<div style="background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden;">'
            f'<div style="width:{bar_w}%;height:100%;background:linear-gradient(90deg,#ef4444,#f97316,#f59e0b,#86efac,#22c55e);border-radius:4px;"></div>'
            f'</div>'
            f'<div style="display:flex;justify-content:space-between;margin-top:5px;">'
            f'<span style="color:#94a3b8;font-size:10px;">Extreme Fear</span>'
            f'<span style="color:#94a3b8;font-size:10px;">Extreme Greed</span>'
            f'</div></div>'
        )
        st.markdown(html, unsafe_allow_html=True)

        if st.button("ⓘ  What is this?", key="fg_info_btn", use_container_width=True):
            st.session_state["show_fg_dialog"] = True

if st.session_state.get("show_fg_dialog"):
    @st.dialog("Fear & Greed Index — Explained")
    def fg_dialog():
        st.markdown(
            '<p style="color:#475569;font-size:13px;line-height:1.7;margin-bottom:18px;">'
            'Published by <b>CNN Business</b> — measures the emotional state of the stock market on a scale '
            'of <b>0 to 100</b> using 7 market indicators: price momentum, price strength, price breadth, '
            'put/call ratio, junk bond demand, market volatility (VIX), and safe haven demand.'
            '</p>',
            unsafe_allow_html=True,
        )
        zones = [
            ("0 – 24",   "Extreme Fear", "#ef4444", "#fef2f2", "Investors are panicking — historically a buying opportunity for contrarians."),
            ("25 – 44",  "Fear",         "#f97316", "#fff7ed", "Caution dominates. Market sentiment is leaning negative."),
            ("45 – 55",  "Neutral",      "#f59e0b", "#fffbeb", "No strong directional bias. Market is in balance."),
            ("56 – 75",  "Greed",        "#22c55e", "#f0fdf4", "Optimism is driving prices. Risk appetite is elevated."),
            ("76 – 100", "Extreme Greed","#16a34a", "#dcfce7", "Market may be overheated. Valuations often stretched."),
        ]
        for score_range, label, color, bg, desc in zones:
            st.markdown(
                '<div style="background:' + bg + ';border-left:3px solid ' + color + ';border-radius:0 6px 6px 0;'
                'padding:10px 14px;margin-bottom:8px;">'
                '<div style="display:flex;align-items:baseline;gap:10px;margin-bottom:3px;">'
                '<span style="color:' + color + ';font-size:13px;font-weight:700;">' + label + '</span>'
                '<span style="color:#94a3b8;font-size:11px;">' + score_range + '</span>'
                '</div>'
                '<span style="color:#475569;font-size:12.5px;line-height:1.5;">' + desc + '</span>'
                '</div>',
                unsafe_allow_html=True,
            )
    fg_dialog()
    st.session_state["show_fg_dialog"] = False

# ── Treasury Yield Curve ───────────────────────────────────────────────────
with right_col:
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Treasury Yield Curve</div>', unsafe_allow_html=True)
    yield_pts = get_yield_curve()
    if yield_pts:
        labels = [p[0] for p in yield_pts]
        values = [p[1] for p in yield_pts]
        # Color: inverted curve = red, normal = green
        is_inverted = values[0] > values[-1]
        yc_color = "#ef4444" if is_inverted else "#22c55e"
        fig_yc = go.Figure()
        fig_yc.add_trace(go.Scatter(
            x=labels, y=values, mode="lines+markers+text",
            line=dict(color=yc_color, width=2),
            marker=dict(color=yc_color, size=7),
            text=[f"{v:.2f}%" for v in values],
            textposition="top center",
            textfont=dict(color="#94a3b8", size=11),
            hovertemplate="%{x}: %{y:.3f}%<extra></extra>",
        ))
        fig_yc.update_layout(
            paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
            margin=dict(l=10,r=10,t=10,b=10), height=180,
            xaxis=dict(showgrid=False, color="#94a3b8", showline=False),
            yaxis=dict(showgrid=True, gridcolor="#e2e8f0", color="#94a3b8",
                       showline=False, tickformat=".2f", ticksuffix="%"),
            showlegend=False,
        )
        st.plotly_chart(fig_yc, width="stretch")
        status = "Inverted — historically precedes recession" if is_inverted else "Normal slope"
        status_color = "#f97316" if is_inverted else "#22c55e"
        st.markdown(f"<p style='color:{status_color};font-size:11px;margin-top:-8px;'>{status}</p>", unsafe_allow_html=True)

    # ── Claude Picks Tracker ───────────────────────────────────────────────────
    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">Claude Picks Tracker</div>', unsafe_allow_html=True)

    history = load_picks_history()

    if not history:
        st.markdown(
            "<p style='color:#94a3b8;font-size:12px;'>No picks recorded yet — check back after today's picks are saved.</p>",
            unsafe_allow_html=True,
        )
    else:
        # Timeframe selector
        TIMEFRAMES = {
            "Past Day":      1,
            "Past Week":     7,
            "Past 2 Weeks": 14,
            "Past Month":   30,
            "Past 3 Months":90,
            "All Time":    9999,
        }
        tf_choice = st.selectbox(
            "Timeframe",
            list(TIMEFRAMES.keys()),
            index=1,
            label_visibility="collapsed",
            key="tracker_tf",
        )
        cutoff = (datetime.now() - timedelta(days=TIMEFRAMES[tf_choice])).strftime("%Y-%m-%d")
        filtered = [e for e in history if e["date"] >= cutoff]

        if not filtered:
            st.markdown(
                f"<p style='color:#94a3b8;font-size:12px;'>No picks in the selected window.</p>",
                unsafe_allow_html=True,
            )
        else:
            # Fetch current prices (batch via fast_info)
            @st.cache_data(ttl=60, show_spinner=False)
            def get_current_prices(syms_tuple):
                prices = {}
                for sym in syms_tuple:
                    try:
                        fi = yf.Ticker(sym).fast_info
                        p  = getattr(fi, "last_price", None)
                        if p:
                            prices[sym] = p
                    except Exception:
                        pass
                return prices

            syms = tuple(sorted({e["sym"] for e in filtered}))
            current_prices = get_current_prices(syms)

            # Build rows: one per pick entry
            rows = []
            for e in filtered:
                sym   = e["sym"]
                name  = e["name"]
                date  = e["date"]
                entry = e["price_at_pick"]
                curr  = current_prices.get(sym)
                if curr and entry:
                    ret = (curr - entry) / entry * 100
                    rows.append((date, sym, name, entry, curr, ret))

            if not rows:
                st.markdown("<p style='color:#94a3b8;font-size:12px;'>Price data unavailable.</p>", unsafe_allow_html=True)
            else:
                # Sort by date desc then sym
                rows.sort(key=lambda x: x[0], reverse=True)

                # Summary stats bar
                rets   = [r[5] for r in rows]
                wins   = sum(1 for r in rets if r > 0)
                losses = sum(1 for r in rets if r <= 0)
                avg_ret = sum(rets) / len(rets)
                avg_color = "#16a34a" if avg_ret >= 0 else "#dc2626"
                avg_sign  = "+" if avg_ret >= 0 else ""

                st.markdown(
                    '<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">'
                    '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 14px;flex:1;min-width:80px;text-align:center;">'
                    '<div style="color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Picks</div>'
                    '<div style="color:#1e3a5c;font-size:18px;font-weight:700;">' + str(len(rows)) + '</div>'
                    '</div>'
                    '<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:8px 14px;flex:1;min-width:80px;text-align:center;">'
                    '<div style="color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Wins</div>'
                    '<div style="color:#16a34a;font-size:18px;font-weight:700;">' + str(wins) + '</div>'
                    '</div>'
                    '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:8px 14px;flex:1;min-width:80px;text-align:center;">'
                    '<div style="color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Losses</div>'
                    '<div style="color:#dc2626;font-size:18px;font-weight:700;">' + str(losses) + '</div>'
                    '</div>'
                    '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 14px;flex:1;min-width:80px;text-align:center;">'
                    '<div style="color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;">Avg Return</div>'
                    '<div style="color:' + avg_color + ';font-size:18px;font-weight:700;">' + avg_sign + f'{avg_ret:.2f}%</div>'
                    '</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

                # Table of individual picks
                hdr = (
                    '<div style="overflow-x:auto;border-radius:7px;border:1px solid #e2e8f0;">'
                    '<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif;font-size:12px;">'
                    '<thead><tr style="background:#f1f5f9;">'
                    '<th style="padding:8px 12px;color:#94a3b8;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:600;">Date</th>'
                    '<th style="padding:8px 12px;color:#94a3b8;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:600;">Ticker</th>'
                    '<th style="padding:8px 12px;color:#94a3b8;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:600;">Entry</th>'
                    '<th style="padding:8px 12px;color:#94a3b8;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:600;">Current</th>'
                    '<th style="padding:8px 12px;color:#94a3b8;text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:600;">Return</th>'
                    '</tr></thead><tbody>'
                )
                body = ""
                for date, sym, name, entry, curr, ret in rows:
                    ret_color = "#16a34a" if ret >= 0 else "#dc2626"
                    ret_sign  = "+" if ret >= 0 else ""
                    ret_arrow = "▲" if ret >= 0 else "▼"
                    # Format date as "Jun 02"
                    try:
                        date_fmt = datetime.strptime(date, "%Y-%m-%d").strftime("%b %d")
                    except Exception:
                        date_fmt = date
                    body += (
                        '<tr style="border-bottom:1px solid #f1f5f9;">'
                        '<td style="padding:8px 12px;color:#94a3b8;">' + date_fmt + '</td>'
                        '<td style="padding:8px 12px;">'
                        '<span style="color:#1e3a5c;font-weight:700;">' + sym + '</span>'
                        '<span style="color:#94a3b8;font-size:11px;margin-left:6px;">' + name[:18] + '</span>'
                        '</td>'
                        '<td style="padding:8px 12px;color:#475569;text-align:right;">$' + f'{entry:,.2f}' + '</td>'
                        '<td style="padding:8px 12px;color:#1e3a5c;font-weight:600;text-align:right;">$' + f'{curr:,.2f}' + '</td>'
                        '<td style="padding:8px 12px;text-align:right;">'
                        '<span style="color:' + ret_color + ';font-weight:700;">' + ret_arrow + ' ' + ret_sign + f'{ret:.2f}%</span>'
                        '</td>'
                        '</tr>'
                    )
                st.markdown(hdr + body + '</tbody></table></div>', unsafe_allow_html=True)

def fetch_info(ticker):
    hit, val = _cache_get(f"info:{ticker}", ttl=120)
    if hit: return val
    result = _yf_with_retry(lambda: yf.Ticker(ticker).info)
    _cache_set(f"info:{ticker}", result)
    return result

def fetch_history(ticker, period="1y", interval="1d"):
    hit, val = _cache_get(f"hist:{ticker}:{period}:{interval}", ttl=60)
    if hit: return val
    prepost = interval in ("1m","2m","5m","15m","30m","60m","90m","1h")
    result = _yf_with_retry(lambda: yf.Ticker(ticker).history(period=period, interval=interval, prepost=prepost))
    _cache_set(f"hist:{ticker}:{period}:{interval}", result)
    return result

def fetch_financials(ticker):
    hit, val = _cache_get(f"fin:{ticker}", ttl=600)
    if hit: return val
    t = yf.Ticker(ticker)
    result = _yf_with_retry(lambda: (t.financials, t.quarterly_financials, t.balance_sheet, t.quarterly_balance_sheet, t.cashflow, t.quarterly_cashflow))
    _cache_set(f"fin:{ticker}", result)
    return result

def fetch_earnings(ticker):
    hit, val = _cache_get(f"earn:{ticker}", ttl=600)
    if hit: return val
    t = yf.Ticker(ticker)
    result = _yf_with_retry(lambda: (t.earnings_history, t.calendar))
    _cache_set(f"earn:{ticker}", result)
    return result

def fetch_news(ticker):
    hit, val = _cache_get(f"news:{ticker}", ttl=900)
    if hit: return val
    result = _yf_with_retry(lambda: yf.Ticker(ticker).news)
    _cache_set(f"news:{ticker}", result)
    return result

def fetch_analyst(ticker):
    hit, val = _cache_get(f"analyst:{ticker}", ttl=3600)
    if hit: return val
    t = yf.Ticker(ticker)
    result = _yf_with_retry(lambda: (t.analyst_price_targets, t.recommendations_summary))
    _cache_set(f"analyst:{ticker}", result)
    return result

def fetch_insider(ticker):
    hit, val = _cache_get(f"insider:{ticker}", ttl=3600)
    if hit: return val
    result = _yf_with_retry(lambda: yf.Ticker(ticker).insider_transactions)
    _cache_set(f"insider:{ticker}", result)
    return result

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY PROFILE — modal dialog
# ══════════════════════════════════════════════════════════════════════════════
@st.dialog("Company Profile", width="large")
def show_profile(ticker):
    with st.spinner(f"Loading {ticker}…"):
        try:
            info = fetch_info(ticker)

            if not info or (info.get("regularMarketPrice") is None and info.get("currentPrice") is None):
                st.error(f"No data found for **{ticker}**. Check the symbol.")
                return

            is_crypto = info.get("quoteType","").upper() == "CRYPTOCURRENCY" or ticker.endswith("-USD") and "-" in ticker

            name     = info.get("longName") or info.get("shortName") or ticker
            sector   = info.get("sector","N/A")
            industry = info.get("industry","N/A")
            exchange = info.get("exchange","N/A")
            currency = info.get("currency","USD")
            website  = info.get("website","")

            price      = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            day_high   = info.get("dayHigh") or info.get("regularMarketDayHigh")
            day_low    = info.get("dayLow") or info.get("regularMarketDayLow")
            w52_high   = info.get("fiftyTwoWeekHigh")
            w52_low    = info.get("fiftyTwoWeekLow")
            volume     = info.get("volume") or info.get("regularMarketVolume")
            avg_vol    = info.get("averageVolume")

            change  = (price - prev_close) if price and prev_close else None
            pct_chg = (change / prev_close * 100) if change and prev_close else None

            market_cap  = info.get("marketCap")
            pe_ratio    = info.get("trailingPE")
            fwd_pe      = info.get("forwardPE")
            eps         = info.get("trailingEps")
            fwd_eps     = info.get("forwardEps")
            pb          = info.get("priceToBook")
            ps          = info.get("priceToSalesTrailing12Months")
            ev_ebitda   = info.get("enterpriseToEbitda")
            beta        = info.get("beta")
            revenue     = info.get("totalRevenue")
            gross_profit= info.get("grossProfits")
            ebitda_v    = info.get("ebitda")
            net_income  = info.get("netIncomeToCommon")
            profit_margin=info.get("profitMargins")
            op_margin   = info.get("operatingMargins")
            gross_margin= info.get("grossMargins")
            roe         = info.get("returnOnEquity")
            roa         = info.get("returnOnAssets")
            rev_growth  = info.get("revenueGrowth")
            earn_growth = info.get("earningsGrowth")
            total_cash  = info.get("totalCash")
            total_debt  = info.get("totalDebt")
            d2e         = info.get("debtToEquity")
            curr_ratio  = info.get("currentRatio")
            fcf_v       = info.get("freeCashflow")
            div_yield   = info.get("dividendYield")
            div_rate    = info.get("dividendRate")
            payout      = info.get("payoutRatio")

            # Static name/meta header (doesn't need to refresh)
            website_html = (
                f'<a href="{website}" target="_blank" style="color:#2563eb;font-size:12px;">'
                f'{website.replace("https://","").replace("http://","").rstrip("/")}</a>'
            ) if website else ""

            st.markdown(
                f'<div style="background:#f8fafc;border:none;border-bottom:2px solid #e2e8f0;border-radius:8px 8px 0 0;padding:18px 28px 10px;">'
                f'<div style="color:#1e3a5c;font-size:26px;font-weight:800;line-height:1.2;margin-bottom:4px;">{name}</div>'
                f'<div style="color:#64748b;font-size:12px;letter-spacing:0.02em;">{ticker}&nbsp;&nbsp;·&nbsp;&nbsp;{exchange}&nbsp;&nbsp;·&nbsp;&nbsp;{sector} › {industry}</div>'
                + (f'<div style="margin-top:4px;">{website_html}</div>' if website_html else '') +
                '</div>',
                unsafe_allow_html=True,
            )

            # Live price block — refreshes every 15 s independently
            @st.fragment(run_every=15)
            def live_price_block():
                try:
                    fi       = yf.Ticker(ticker).fast_info
                    lp       = getattr(fi, "last_price", None) or price
                    pc       = getattr(fi, "previous_close", None) or prev_close
                    dh       = getattr(fi, "day_high", None) or day_high
                    dl       = getattr(fi, "day_low",  None) or day_low
                    chg      = (lp - pc) if lp and pc else 0
                    pct      = (chg / pc * 100) if pc else 0
                    sign     = "+" if chg >= 0 else ""
                    clr      = "#22c55e" if chg >= 0 else "#ef4444"
                    arr      = "▲" if chg >= 0 else "▼"
                    range_str = f"${dl:,.2f} – ${dh:,.2f}" if dl and dh else "—"
                except Exception:
                    lp, pc, chg, pct, sign, clr, arr, range_str = price, prev_close, change, pct_chg or 0, chg_sign if 'chg_sign' in dir() else "", "#94a3b8", "—", "—"

                st.markdown(
                    f'<div style="background:#f8fafc;border-radius:0 0 8px 8px;padding:12px 28px 18px;'
                    f'border-bottom:2px solid #e2e8f0;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
                    f'<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">'
                    f'<span style="color:#1e3a5c;font-size:36px;font-weight:800;letter-spacing:-0.5px;line-height:1;">{currency} {lp:,.2f}</span>'
                    f'<span style="color:{clr};font-size:16px;font-weight:700;">{arr} {sign}{chg:,.2f} &nbsp; ({sign}{pct:.2f}%)</span>'
                    f'</div>'
                    f'<div style="display:flex;gap:20px;margin-top:6px;flex-wrap:wrap;">'
                    f'<span style="color:#94a3b8;font-size:11px;">Prev close &nbsp;<b style="color:#64748b;">{currency} {pc:,.2f}</b></span>'
                    f'<span style="color:#94a3b8;font-size:11px;">Day range &nbsp;<b style="color:#64748b;">{range_str}</b></span>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            live_price_block()

            wl_label = "In Watchlist" if ticker in st.session_state.watchlist else "+ Watchlist"
            if st.button(wl_label, key="wl_btn"):
                if ticker in st.session_state.watchlist:
                    st.session_state.watchlist.remove(ticker)
                else:
                    st.session_state.watchlist.append(ticker)
                save_watchlist(st.session_state.watchlist)
                st.rerun()

            # Chart — refreshes every 30 s so the 1D candles stay current
            st.markdown('<div class="section-header">Price History</div>', unsafe_allow_html=True)
            PERIOD_CONFIG = {
                "1D":  ("1d",  "5m",   "<b>%{x|%H:%M}</b><br>$%{y:.2f}"),
                "5D":  ("5d",  "30m",  "<b>%{x|%b %d %H:%M}</b><br>$%{y:.2f}"),
                "1M":  ("1mo", "1d",   "<b>%{x|%b %d, %Y}</b><br>$%{y:.2f}"),
                "3M":  ("3mo", "1d",   "<b>%{x|%b %d, %Y}</b><br>$%{y:.2f}"),
                "6M":  ("6mo", "1d",   "<b>%{x|%b %d, %Y}</b><br>$%{y:.2f}"),
                "1Y":  ("1y",  "1d",   "<b>%{x|%b %d, %Y}</b><br>$%{y:.2f}"),
                "5Y":  ("5y",  "1wk",  "<b>%{x|%b %Y}</b><br>$%{y:.2f}"),
                "All": ("max", "1mo",  "<b>%{x|%Y}</b><br>$%{y:.2f}"),
            }
            period_choice = st.radio("Chart period", list(PERIOD_CONFIG.keys()), horizontal=True, index=5, label_visibility="collapsed")

            @st.fragment(run_every=30)
            def live_chart(period_choice=period_choice):
                yf_period, yf_interval, hover_fmt = PERIOD_CONFIG[period_choice]
                # bust the yfinance cache on every fragment refresh for short intervals
                fetch_history.clear() if yf_interval in ("5m","30m") else None
                hist = fetch_history(ticker, yf_period, yf_interval)
                if not hist.empty:
                    if yf_interval in ("5m", "15m", "30m", "1h"):
                        freq_map = {"5m":"5min","15m":"15min","30m":"30min","1h":"1h"}
                        full_idx = pd.date_range(hist.index[0], hist.index[-1], freq=freq_map[yf_interval])
                        hist = hist.reindex(full_idx).ffill()

                    lc  = "#22c55e" if hist["Close"].iloc[-1] >= hist["Close"].iloc[0] else "#ef4444"
                    rgb = "34,197,94" if lc == "#22c55e" else "239,68,68"

                    all_lows  = hist["Low"].dropna()
                    all_highs = hist["High"].dropna()
                    if not all_lows.empty and not all_highs.empty:
                        y_min   = all_lows.min()
                        y_max   = all_highs.max()
                        padding = (y_max - y_min) * 0.15 if y_max > y_min else y_max * 0.01
                        y_range = [y_min - padding, y_max + padding]
                    else:
                        y_range = None

                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=list(hist.index) + list(hist.index[::-1]),
                        y=list(hist["High"]) + list(hist["Low"][::-1]),
                        fill="toself", fillcolor=f"rgba({rgb},0.10)",
                        line=dict(width=0), hoverinfo="skip", showlegend=False,
                    ))
                    fig.add_trace(go.Scatter(
                        x=hist.index, y=hist["Close"],
                        mode="lines", line=dict(color=lc, width=2),
                        hovertemplate=hover_fmt + "<extra></extra>",
                        connectgaps=True, name="Close",
                    ))
                    fig.update_layout(
                        paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
                        margin=dict(l=10, r=10, t=10, b=10),
                        height=300, hovermode="x unified", showlegend=False,
                    )
                    ax = dict(showgrid=True, gridcolor="#d1d9e0", color="#1e293b",
                              showline=True, linecolor="#94a3b8", linewidth=1,
                              zeroline=False, tickfont=dict(size=11, color="#1e293b", family="Inter,sans-serif"))
                    fig.update_xaxes(**ax)
                    fig.update_yaxes(**ax, tickformat="$,.2f", range=y_range)
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.markdown("<p style='color:#64748b;'>No price data available.</p>", unsafe_allow_html=True)

            live_chart()

            # Key stats
            st.markdown('<div class="section-header">Key Statistics</div>', unsafe_allow_html=True)
            c1,c2,c3,c4 = st.columns(4)
            with c1:
                metric_card("Market Cap", fmt_large(market_cap))
                metric_card("52-Wk High", fmt(w52_high,prefix="$"))
                metric_card("52-Wk Low",  fmt(w52_low,prefix="$"))
            with c2:
                metric_card("Day Range", f"{fmt(day_low,prefix='$')} – {fmt(day_high,prefix='$')}")
                metric_card("Volume",    f"{volume:,.0f}" if volume else "N/A")
                metric_card("Avg Volume",f"{avg_vol:,.0f}" if avg_vol else "N/A")
            if is_crypto:
                with c3:
                    circ = info.get("circulatingSupply")
                    total_supply = info.get("totalSupply")
                    max_supply   = info.get("maxSupply")
                    metric_card("Circulating Supply", f"{circ:,.0f}" if circ else "N/A")
                    metric_card("Total Supply",        f"{total_supply:,.0f}" if total_supply else "N/A")
                    metric_card("Max Supply",           f"{max_supply:,.0f}" if max_supply else "∞")
                with c4:
                    vol_24h = info.get("volume24Hr") or info.get("regularMarketVolume")
                    vol_all = info.get("volumeAllCurrencies")
                    start_d = info.get("startDate")
                    start_str = datetime.fromtimestamp(start_d).strftime("%b %Y") if start_d else "N/A"
                    metric_card("24h Volume",    fmt_large(vol_24h) if vol_24h else "N/A")
                    metric_card("Launch Date",   start_str)
                    metric_card("Beta",          fmt(beta))
            else:
                with c3:
                    metric_card("P/E (TTM)", fmt(pe_ratio))
                    metric_card("Fwd P/E",   fmt(fwd_pe))
                    metric_card("P/B",       fmt(pb))
                with c4:
                    metric_card("EPS (TTM)", fmt(eps,prefix="$"))
                    metric_card("Fwd EPS",   fmt(fwd_eps,prefix="$"))
                    metric_card("Beta",      fmt(beta))

            if not is_crypto:
                # Statements
                st.markdown('<div class="section-header">Financial Statements (yfinance · ~4 years)</div>', unsafe_allow_html=True)
                freq = st.radio("Freq", ["Annual","Quarterly"], horizontal=True, label_visibility="collapsed")
                annual = freq=="Annual"
                t1,t2,t3 = st.tabs(["Income Statement","Balance Sheet","Cash Flow"])
                annual_is, qtr_is, annual_bs, qtr_bs, annual_cf, qtr_cf = fetch_financials(ticker)
                with t1: render_fin_table(annual_is if annual else qtr_is)
                with t2: render_fin_table(annual_bs if annual else qtr_bs)
                with t3: render_fin_table(annual_cf if annual else qtr_cf)

                # EDGAR historical
                st.markdown('<div class="section-header">Historical Financials (SEC EDGAR · back to ~2001)</div>', unsafe_allow_html=True)
                try:
                    cik = get_cik(ticker)
                    if not cik:
                        st.markdown("<p style='color:#64748b;'>CIK not found for this ticker.</p>", unsafe_allow_html=True)
                    else:
                        ef = get_edgar_facts(cik)
                        df_is_e = extract_edgar_annual(ef, EDGAR_INCOME)
                        df_bs_e = extract_edgar_annual(ef, EDGAR_BALANCE)
                        cf_map  = {k:v for k,v in EDGAR_CASHFLOW.items() if v}
                        df_cf_e = extract_edgar_annual(ef, cf_map)
                        if not df_cf_e.empty and "Operating Cash Flow" in df_cf_e.index and "Capital Expenditures" in df_cf_e.index:
                            df_cf_e.loc["Free Cash Flow"] = df_cf_e.loc["Operating Cash Flow"].subtract(df_cf_e.loc["Capital Expenditures"].abs())
                            df_cf_e = df_cf_e.reindex([k for k in EDGAR_CASHFLOW if k in df_cf_e.index])
                        h1e,h2e,h3e = st.tabs(["Income Statement","Balance Sheet","Cash Flow"])
                        with h1e: render_edgar_table(df_is_e)
                        with h2e: render_edgar_table(df_bs_e)
                        with h3e: render_edgar_table(df_cf_e)
                except Exception as e:
                    st.markdown(f"<p style='color:#64748b;'>EDGAR unavailable: {e}</p>", unsafe_allow_html=True)

            # Summary cards
            st.markdown('<div class="section-header">Financial Summary</div>', unsafe_allow_html=True)
            c1,c2,c3 = st.columns(3)
            with c1:
                st.markdown("<p style='color:#94a3b8;font-size:11px;font-weight:600;margin-bottom:4px;text-transform:uppercase;'>Income</p>", unsafe_allow_html=True)
                metric_card("Revenue (TTM)", fmt_large(revenue))
                metric_card("Gross Profit",  fmt_large(gross_profit))
                metric_card("EBITDA",        fmt_large(ebitda_v))
                metric_card("Net Income",    fmt_large(net_income))
            with c2:
                st.markdown("<p style='color:#94a3b8;font-size:11px;font-weight:600;margin-bottom:4px;text-transform:uppercase;'>Margins & Returns</p>", unsafe_allow_html=True)
                metric_card("Gross Margin",     fmt(gross_margin*100 if gross_margin else None,suffix="%") if gross_margin else "N/A")
                metric_card("Operating Margin", fmt(op_margin*100    if op_margin    else None,suffix="%") if op_margin    else "N/A")
                metric_card("Net Margin",       fmt(profit_margin*100 if profit_margin else None,suffix="%") if profit_margin else "N/A")
                metric_card("ROE", fmt(roe*100 if roe else None,suffix="%") if roe else "N/A")
                metric_card("ROA", fmt(roa*100 if roa else None,suffix="%") if roa else "N/A")
            with c3:
                st.markdown("<p style='color:#94a3b8;font-size:11px;font-weight:600;margin-bottom:4px;text-transform:uppercase;'>Balance Sheet</p>", unsafe_allow_html=True)
                metric_card("Cash",           fmt_large(total_cash))
                metric_card("Total Debt",     fmt_large(total_debt))
                metric_card("Debt / Equity",  fmt(d2e))
                metric_card("Current Ratio",  fmt(curr_ratio))
                metric_card("Free Cash Flow", fmt_large(fcf_v))

            # Valuation & Dividends
            st.markdown('<div class="section-header">Valuation & Dividends</div>', unsafe_allow_html=True)
            c1,c2 = st.columns(2)
            with c1:
                metric_card("EV / EBITDA",    fmt(ev_ebitda))
                metric_card("P/S Ratio",      fmt(ps))
                metric_card("Revenue Growth", fmt(rev_growth*100  if rev_growth  else None,suffix="%") if rev_growth  else "N/A")
                metric_card("EPS Growth",     fmt(earn_growth*100 if earn_growth else None,suffix="%") if earn_growth else "N/A")
            with c2:
                metric_card("Dividend Yield", fmt(div_yield*100 if div_yield else None,suffix="%") if div_yield else "N/A")
                metric_card("Dividend Rate",  fmt(div_rate,prefix="$") if div_rate else "N/A")
                metric_card("Payout Ratio",   fmt(payout*100 if payout else None,suffix="%") if payout else "N/A")

            if not is_crypto:
                # Earnings history
                st.markdown('<div class="section-header">Earnings History</div>', unsafe_allow_html=True)
                try:
                    earnings_df, calendar = fetch_earnings(ticker)
                    if calendar is not None:
                        nd = None
                        if isinstance(calendar, dict):
                            nd = calendar.get("Earnings Date")
                            if isinstance(nd,list): nd = nd[0] if nd else None
                        elif isinstance(calendar, pd.DataFrame) and "Earnings Date" in calendar.columns:
                            nd = calendar["Earnings Date"].iloc[0]
                        if nd:
                            nd = pd.to_datetime(nd)
                            days_away = (nd - pd.Timestamp.now()).days
                            tag = f"in {days_away} days" if days_away > 0 else "recently"
                            st.markdown(f"<p style='color:#5a9fd4;font-size:13px;'>Next earnings: <b>{nd.strftime('%b %d, %Y')}</b> ({tag})</p>", unsafe_allow_html=True)
                    if earnings_df is not None and not earnings_df.empty:
                        df_e = earnings_df.sort_index(ascending=False).head(8)
                        dates,actuals,estimates,surprises = [],[],[],[]
                        for idx, row in df_e.iterrows():
                            dt = pd.to_datetime(idx).strftime("%b '%y") if not isinstance(idx,str) else idx
                            actual   = row.get("epsActual")      if "epsActual"      in df_e.columns else None
                            estimate = row.get("epsEstimate")    if "epsEstimate"    in df_e.columns else None
                            surprise = row.get("surprisePercent") if "surprisePercent" in df_e.columns else None
                            dates.append(dt); actuals.append(actual); estimates.append(estimate); surprises.append(surprise)
                        fig2 = go.Figure()
                        fig2.add_trace(go.Bar(x=dates[::-1],y=estimates[::-1],name="Estimate",marker_color="#1e3a5f",hovertemplate="<b>%{x}</b><br>Est: $%{y:.2f}<extra></extra>"))
                        fig2.add_trace(go.Bar(x=dates[::-1],y=actuals[::-1],name="Actual",
                            marker_color=["#22c55e" if (a and e and a>=e) else "#ef4444" for a,e in zip(actuals[::-1],estimates[::-1])],
                            hovertemplate="<b>%{x}</b><br>Act: $%{y:.2f}<extra></extra>"))
                        fig2.update_layout(paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",barmode="overlay",
                            margin=dict(l=10,r=10,t=10,b=10),height=220,
                            xaxis=dict(showgrid=False, color="#1e293b", showline=True, linecolor="#94a3b8", tickfont=dict(size=11, color="#1e293b", family="Inter,sans-serif")),
                            yaxis=dict(showgrid=True, gridcolor="#d1d9e0", color="#1e293b", showline=True, linecolor="#94a3b8", title="EPS ($)", tickfont=dict(size=11, color="#1e293b", family="Inter,sans-serif")),
                            legend=dict(bgcolor="#ffffff",font=dict(color="#475569")),hovermode="x unified")
                        st.plotly_chart(fig2, width="stretch")
                        rows_html = ""
                        for dt,actual,estimate,surprise in zip(dates,actuals,estimates,surprises):
                            bm = ""
                            if actual is not None and estimate is not None:
                                if actual>estimate: bm='<span class="beat">BEAT</span>'
                                elif actual<estimate: bm='<span class="miss">MISS</span>'
                                else: bm='<span class="inline">IN-LINE</span>'
                            surp = f"{surprise:+.1f}%" if surprise is not None and not pd.isna(surprise) else "—"
                            rows_html += f'<tr style="border-bottom:1px solid #0a1628;"><td style="padding:8px 12px;color:#cbd5e1;">{dt}</td><td style="padding:8px 12px;color:#f1f5f9;text-align:right;">{fmt(actual,prefix="$") if actual is not None else "—"}</td><td style="padding:8px 12px;color:#94a3b8;text-align:right;">{fmt(estimate,prefix="$") if estimate is not None else "—"}</td><td style="padding:8px 12px;text-align:right;">{surp}</td><td style="padding:8px 12px;text-align:center;">{bm}</td></tr>'
                        st.markdown(f'<table style="width:100%;border-collapse:collapse;background:#ffffff;border-radius:6px;overflow:hidden;border:1px solid #e2e8f0;"><thead><tr style="background:#f1f5f9;"><th style="padding:9px 12px;color:#64748b;text-align:left;font-size:11px;text-transform:uppercase;">Quarter</th><th style="padding:9px 12px;color:#64748b;text-align:right;font-size:11px;text-transform:uppercase;">EPS Actual</th><th style="padding:9px 12px;color:#64748b;text-align:right;font-size:11px;text-transform:uppercase;">EPS Estimate</th><th style="padding:9px 12px;color:#64748b;text-align:right;font-size:11px;text-transform:uppercase;">Surprise</th><th style="padding:9px 12px;color:#64748b;text-align:center;font-size:11px;text-transform:uppercase;">Result</th></tr></thead><tbody>{rows_html}</tbody></table>', unsafe_allow_html=True)
                    else:
                        st.markdown("<p style='color:#64748b;'>No earnings history available.</p>", unsafe_allow_html=True)
                except Exception as e:
                    st.markdown(f"<p style='color:#64748b;'>Earnings unavailable: {e}</p>", unsafe_allow_html=True)

                # Analyst Ratings & Price Targets
                st.markdown('<div class="section-header">Analyst Ratings &amp; Price Targets</div>', unsafe_allow_html=True)
                try:
                    price_targets, rec_summary = fetch_analyst(ticker)
                    has_targets = price_targets and isinstance(price_targets, dict) and price_targets.get("mean")
                    has_recs    = rec_summary is not None and not (hasattr(rec_summary, "empty") and rec_summary.empty)

                    if has_targets:
                        current_p = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                        mean_t    = price_targets.get("mean", 0)
                        low_t     = price_targets.get("low", 0)
                        high_t    = price_targets.get("high", 0)
                        upside    = ((mean_t - current_p) / current_p * 100) if current_p else 0
                        up_color  = "#22c55e" if upside >= 0 else "#ef4444"
                        up_sign   = "+" if upside >= 0 else ""
                        ta1, ta2, ta3, ta4 = st.columns(4)
                        with ta1:
                            st.markdown(f'<div class="metric-card"><div class="metric-label">Mean Target</div><div class="metric-value">${mean_t:,.2f}</div></div>', unsafe_allow_html=True)
                        with ta2:
                            st.markdown(f'<div class="metric-card"><div class="metric-label">Low Target</div><div class="metric-value">${low_t:,.2f}</div></div>', unsafe_allow_html=True)
                        with ta3:
                            st.markdown(f'<div class="metric-card"><div class="metric-label">High Target</div><div class="metric-value">${high_t:,.2f}</div></div>', unsafe_allow_html=True)
                        with ta4:
                            st.markdown(f'<div class="metric-card"><div class="metric-label">Upside (mean)</div><div class="metric-value" style="color:{up_color};">{up_sign}{upside:.1f}%</div></div>', unsafe_allow_html=True)

                    if has_recs:
                        try:
                            row0 = rec_summary.iloc[0] if hasattr(rec_summary, "iloc") else None
                            if row0 is not None:
                                strong_buy  = int(row0.get("strongBuy", 0))
                                buy         = int(row0.get("buy", 0))
                                hold        = int(row0.get("hold", 0))
                                sell        = int(row0.get("sell", 0))
                                strong_sell = int(row0.get("strongSell", 0))
                                total       = strong_buy + buy + hold + sell + strong_sell or 1
                                bars = [
                                    ("Strong Buy",  strong_buy,  "#16a34a"),
                                    ("Buy",         buy,         "#22c55e"),
                                    ("Hold",        hold,        "#7a9abf"),
                                    ("Sell",        sell,        "#ef4444"),
                                    ("Strong Sell", strong_sell, "#991b1b"),
                                ]
                                st.markdown("<div style='margin-top:10px;'>", unsafe_allow_html=True)
                                bar_html = "<div style='display:flex;gap:3px;height:28px;border-radius:6px;overflow:hidden;margin-bottom:6px;'>"
                                for lbl, count, color in bars:
                                    if count > 0:
                                        pct_b = count / total * 100
                                        bar_html += f'<div style="flex:{pct_b};background:{color};display:flex;align-items:center;justify-content:center;"><span style="color:white;font-size:10px;font-weight:700;">{count}</span></div>'
                                bar_html += "</div>"
                                label_html = "<div style='display:flex;gap:12px;flex-wrap:wrap;'>"
                                for lbl, count, color in bars:
                                    if count > 0:
                                        label_html += f'<span style="color:{color};font-size:11px;font-weight:600;">&#9679; {lbl}: {count}</span>'
                                label_html += "</div>"
                                st.markdown(bar_html + label_html + "</div>", unsafe_allow_html=True)
                        except Exception:
                            pass

                    if not has_targets and not has_recs:
                        st.markdown("<p style='color:#64748b;font-size:12px;'>No analyst data available.</p>", unsafe_allow_html=True)
                except Exception:
                    st.markdown("<p style='color:#64748b;'>Analyst data unavailable.</p>", unsafe_allow_html=True)

                # Insider Transactions
                st.markdown('<div class="section-header">Insider Transactions</div>', unsafe_allow_html=True)
                try:
                    insider_df = fetch_insider(ticker)
                    if insider_df is not None and not insider_df.empty:
                        rows_html = ""
                        for _, row in insider_df.head(12).iterrows():
                            date  = str(row.get("Start Date", ""))[:10]
                            iname = str(row.get("Insider", ""))[:28]
                            pos   = str(row.get("Position", ""))[:20]
                            text  = str(row.get("Text", ""))
                            shares= row.get("Shares", 0)
                            value = row.get("Value", 0)
                            tl = text.lower()
                            if any(w in tl for w in ("purchase","bought","acquired","buy")):
                                txn_label, txn_color = "Buy", "#22c55e"
                            elif any(w in tl for w in ("sale","sold","dispose","gift")):
                                txn_label, txn_color = ("Sell", "#ef4444") if ("sale" in tl or "sold" in tl) else ("Gift", "#94a3b8")
                            else:
                                txn_label, txn_color = "Other", "#64748b"
                            shares_fmt = f"{int(shares):,}" if shares and shares == shares else "—"
                            value_fmt  = fmt_large(value) if value and value == value and value > 0 else "—"
                            rows_html += (
                                f'<tr><td style="padding:7px 10px;color:#94a3b8;font-size:11px;border-bottom:1px solid #e2e8f0;white-space:nowrap;">{date}</td>'
                                f'<td style="padding:7px 10px;color:#1e3a5c;font-size:12px;border-bottom:1px solid #e2e8f0;">{iname}</td>'
                                f'<td style="padding:7px 10px;color:#64748b;font-size:11px;border-bottom:1px solid #e2e8f0;">{pos}</td>'
                                f'<td style="padding:7px 10px;border-bottom:1px solid #e2e8f0;"><span style="color:{txn_color};font-size:11px;font-weight:700;background:{txn_color}22;padding:2px 8px;border-radius:4px;">{txn_label}</span></td>'
                                f'<td style="padding:7px 10px;color:#1e3a5c;font-size:12px;border-bottom:1px solid #e2e8f0;text-align:right;">{shares_fmt}</td>'
                                f'<td style="padding:7px 10px;color:#1e3a5c;font-size:12px;border-bottom:1px solid #e2e8f0;text-align:right;">{value_fmt}</td></tr>'
                            )
                        hdrs = "".join(f'<th style="padding:8px 10px;color:#64748b;text-align:left;font-size:11px;text-transform:uppercase;background:#f1f5f9;border-bottom:1px solid #e2e8f0;">{c}</th>' for c in ["Date","Insider","Position","Type","Shares","Value"])
                        st.markdown(f'<div style="overflow-x:auto;border-radius:8px;border:1px solid #e2e8f0;"><table style="width:100%;border-collapse:collapse;"><thead><tr>{hdrs}</tr></thead><tbody>{rows_html}</tbody></table></div>', unsafe_allow_html=True)
                    else:
                        st.markdown("<p style='color:#64748b;font-size:12px;'>No recent insider transactions.</p>", unsafe_allow_html=True)
                except Exception:
                    st.markdown("<p style='color:#64748b;font-size:12px;'>Insider data unavailable.</p>", unsafe_allow_html=True)

            # Company news
            st.markdown('<div class="section-header">Company News</div>', unsafe_allow_html=True)
            try:
                news = fetch_news(ticker)
                if news:
                    for article in news[:8]:
                        content = article.get("content",{})
                        title   = content.get("title") or article.get("title","")
                        url = ""
                        cp = content.get("canonicalUrl",{})
                        if isinstance(cp,dict): url = cp.get("url","")
                        if not url:
                            ct = content.get("clickThroughUrl",{})
                            url = ct.get("url","") if isinstance(ct,dict) else ""
                        if not url: url = article.get("link","")
                        pub = content.get("pubDate") or article.get("providerPublishTime")
                        try:
                            dt_str = datetime.fromtimestamp(pub).strftime("%b %d  %H:%M") if isinstance(pub,(int,float)) else pd.to_datetime(pub).strftime("%b %d  %H:%M")
                        except Exception:
                            dt_str = ""
                        provider = content.get("provider",{})
                        source = provider.get("displayName","") if isinstance(provider,dict) else article.get("publisher","")
                        t_html = f'<a href="{url}" target="_blank">{title}</a>' if url else title
                        st.markdown(f'<div class="news-card"><div class="news-title">{t_html}</div><div class="news-meta">{source}{"&nbsp;·&nbsp;" if source and dt_str else ""}{dt_str}</div></div>', unsafe_allow_html=True)
                else:
                    st.markdown("<p style='color:#64748b;'>No recent news.</p>", unsafe_allow_html=True)
            except Exception as e:
                st.markdown(f"<p style='color:#64748b;'>News unavailable: {e}</p>", unsafe_allow_html=True)

            # About
            summary_text = info.get("longBusinessSummary")
            if summary_text:
                st.markdown('<div class="section-header">About</div>', unsafe_allow_html=True)
                with st.expander(f"About {name}", expanded=False):
                    st.markdown(f"<p style='color:#475569;line-height:1.75;font-size:13px;'>{summary_text}</p>", unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Error loading {ticker}: {e}")

# Trigger dialog when a company is selected — clear immediately so auto-refresh doesn't reopen it
if st.session_state.get("open_ticker"):
    ticker_to_show = st.session_state["open_ticker"]
    st.session_state["open_ticker"] = None
    show_profile(ticker_to_show)

# Hider: zero-height iframe that watches for CHIP.TRIGGER buttons and hides them instantly
components.html("""
<script>
function hideChipTriggers() {
    const buttons = window.parent.document.querySelectorAll('button');
    buttons.forEach(btn => {
        if (btn.textContent.trim().startsWith('CHIP.TRIGGER.') || btn.textContent.trim().startsWith('MOVER.')) {
            const wrap = btn.closest('[data-testid="stButton"]');
            if (wrap) wrap.style.cssText = 'display:none!important;height:0!important;margin:0!important;padding:0!important;';
        }
    });
}
hideChipTriggers();
new MutationObserver(hideChipTriggers).observe(
    window.parent.document.body, {childList: true, subtree: true}
);
</script>
""", height=0, scrolling=False)

# Hidden trigger buttons — found and clicked by JS in the chips iframe
for _, sym in MARKET_TICKERS:
    if st.button(f"CHIP.TRIGGER.{sym}", key=f"hiddenchip_{sym}"):
        st.session_state["open_ticker"] = sym
        st.rerun()

# Hidden mover trigger buttons — found and clicked by JS in the movers iframe
_gainers_hidden, _losers_hidden = get_top_movers()
for sym, _, _ in (_gainers_hidden + _losers_hidden):
    if st.button(f"MOVER.{sym}", key=f"mover_{sym}"):
        st.session_state["open_ticker"] = sym
        st.rerun()
