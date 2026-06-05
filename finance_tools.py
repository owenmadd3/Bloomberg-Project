import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
import pandas as pd
import re
import requests
import time
import os
from difflib import get_close_matches


st.set_page_config(
    page_title="Finance Tools",
    page_icon=None,
    layout="wide",
)

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
    "net debt":                      "Net Debt",
    "roe":                           "ROE %",
    "return on equity":              "ROE %",
    "roa":                           "ROA %",
    "return on assets":              "ROA %",
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
    "5 year pretax income":          "5-Year Avg Pretax Income",
    "5yr pretax income":             "5-Year Avg Pretax Income",
    "5-year pretax income":          "5-Year Avg Pretax Income",
    "5 year pre tax income":         "5-Year Avg Pretax Income",
    "5-year pre-tax income":         "5-Year Avg Pretax Income",
    "average pretax income":         "5-Year Avg Pretax Income",
    "avg pretax income":             "5-Year Avg Pretax Income",
    "5 year pretax net income":      "5-Year Avg Pretax Income",
    "5yr pretax net income":         "5-Year Avg Pretax Income",
    "5-year pretax net income":      "5-Year Avg Pretax Income",
    "average pretax net income":     "5-Year Avg Pretax Income",
    "avg pretax net income":         "5-Year Avg Pretax Income",
    "price to book":                 "P/B Ratio",
    "price-to-book":                 "P/B Ratio",
    "p/b ratio":                     "P/B Ratio",
    "p/b":                           "P/B Ratio",
    "pb ratio":                      "P/B Ratio",
    "price book":                    "P/B Ratio",
    "price to book value":           "P/B Ratio",
    "price to sales":                "P/S Ratio",
    "price-to-sales":                "P/S Ratio",
    "p/s ratio":                     "P/S Ratio",
    "p/s":                           "P/S Ratio",
    "ps ratio":                      "P/S Ratio",
    "price sales":                   "P/S Ratio",
    "price to revenue":              "P/S Ratio",
    "price to earnings":             "P/E Ratio",
    "price-to-earnings":             "P/E Ratio",
    "p/e ratio":                     "P/E Ratio",
    "pe ratio":                      "P/E Ratio",
    "price earnings":                "P/E Ratio",
    "price to free cash flow":       "P/FCF Ratio",
    "price-to-free-cash-flow":       "P/FCF Ratio",
    "p/fcf":                         "P/FCF Ratio",
    "price fcf":                     "P/FCF Ratio",
    "ev/ebitda":                     "EV/EBITDA",
    "ev ebitda":                     "EV/EBITDA",
    "enterprise value ebitda":       "EV/EBITDA",
    "enterprise value to ebitda":    "EV/EBITDA",
    "enterprise value":              "Enterprise Value",
    "market cap":                    "Market Cap",
    "market capitalization":         "Market Cap",
    "earnings yield":                "Earnings Yield %",
    "earning yield":                 "Earnings Yield %",
    "earnings yield %":              "Earnings Yield %",
    "eps yield":                     "Earnings Yield %",
    "e/p ratio":                     "Earnings Yield %",
    "e/p":                           "Earnings Yield %",
    "inverse pe":                    "Earnings Yield %",
    "inverse p/e":                   "Earnings Yield %",
    "10 year roe":                   "10-Year Avg ROE %",
    "10yr roe":                      "10-Year Avg ROE %",
    "10-year roe":                   "10-Year Avg ROE %",
    "10 year return on equity":      "10-Year Avg ROE %",
    "10yr return on equity":         "10-Year Avg ROE %",
    "10-year return on equity":      "10-Year Avg ROE %",
    "average roe":                   "10-Year Avg ROE %",
    "avg roe":                       "10-Year Avg ROE %",
    "long term roe":                 "10-Year Avg ROE %",
    "long-term roe":                 "10-Year Avg ROE %",
    "decade roe":                    "10-Year Avg ROE %",
}

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
    "berkshire": "BRK-B", "brk": "BRK-B", "brk-b": "BRK-B", "brk.b": "BRK-B",
    "exxon": "XOM", "exxonmobil": "XOM",
    "walmart": "WMT",
    "johnson": "JNJ",
    "procter": "PG", "procter and gamble": "PG",
    "mastercard": "MA",
    "visa": "V", "v": "V",
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

def resolve_company_ticker(query):
    q = query.strip()
    if not q:
        return None
    q_up  = q.upper()
    q_low = q.lower()
    companies = get_company_list()
    for sym, name in companies:
        if sym == q_up:
            return sym, name
    for sym, name in companies:
        if name.lower() == q_low:
            return sym, name
    if len(q) >= 3:
        starts = [(sym, name) for sym, name in companies if name.lower().startswith(q_low)]
        if starts:
            starts.sort(key=lambda x: len(x[1]))
            return starts[0]
    ticker_starts = [(sym, name) for sym, name in companies if sym.startswith(q_up)]
    if ticker_starts:
        ticker_starts.sort(key=lambda x: len(x[0]))
        return ticker_starts[0]
    if len(q) >= 4:
        word_match = [(sym, name) for sym, name in companies
                      if re.search(r'\b' + re.escape(q_low) + r'\b', name.lower())]
        if word_match:
            word_match.sort(key=lambda x: len(x[1]))
            return word_match[0]
    if len(q) >= 4:
        names_lower = [name.lower() for _, name in companies]
        matches = get_close_matches(q_low, names_lower, n=1, cutoff=0.7)
        if matches:
            idx = names_lower.index(matches[0])
            return companies[idx]
    return None

def extract_ticker_from_question(question, provided_ticker=None):
    companies = get_company_list()
    ticker_set = {sym for sym, _ in companies}
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
    # Match hyphenated tickers (BRK-B), standard tickers (AAPL), and single-letter tickers (V, F, T)
    tokens = re.findall(r'\b([A-Z]{1,5}(?:-[A-Z]{1,2})?)\b', question)
    for tok in tokens:
        if tok in ticker_set:
            name = next((n for s, n in companies if s == tok), tok)
            return tok, name
    for informal, sym in sorted(NAME_OVERRIDES.items(), key=lambda x: -len(x[0])):
        if informal in q_low:
            name = next((n for s, n in companies if s == sym), sym)
            return sym, name
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
    labels_lower = [l.lower() for l in available_labels]
    for keyword in sorted(SEARCH_KEYWORD_MAP, key=len, reverse=True):
        if keyword in q_lower:
            target = SEARCH_KEYWORD_MAP[keyword]
            if target in available_labels:
                return target
            match = next((l for l in available_labels if l.lower() == target.lower()), None)
            if match:
                return match
            return None
    filler = (r'\b(what|was|is|the|in|of|for|and|how|did|does|company|their|its|s|tell|'
              r'show|give|report|me|much|please|find|get|fetch|look|up)\b')
    core = re.sub(filler, ' ', q_lower)
    core = re.sub(r'\b[a-z]{1,4}\b', ' ', core)
    core = re.sub(r'\b20\d{2}\b', '', core)
    core = re.sub(r'[^a-z\s]', ' ', core)
    core = re.sub(r'\s+', ' ', core).strip()
    if len(core) >= 4:
        matches = get_close_matches(core, labels_lower, n=1, cutoff=0.6)
        if matches:
            return next((l for l in available_labels if l.lower() == matches[0]), None)
    return None

def _add_derived_metrics(df):
    def safe_row(label):
        if label in df.index:
            return df.loc[label].fillna(0)
        return pd.Series(0, index=df.columns)
    if "Operating Income" in df.index and "Depreciation & Amort" in df.index:
        df.loc["EBITDA"] = safe_row("Operating Income") + safe_row("Depreciation & Amort").abs()
    if "Operating Income" in df.index:
        df.loc["EBIT"] = df.loc["Operating Income"]
    if "Operating Cash Flow" in df.index and "Capital Expenditures" in df.index:
        df.loc["Free Cash Flow"] = safe_row("Operating Cash Flow") - safe_row("Capital Expenditures").abs()
    if "Long-Term Debt" in df.index or "Short-Term Debt" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        df.loc["Total Debt"] = total_debt
    if "Long-Term Debt" in df.index or "Short-Term Debt" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        df.loc["Net Debt"] = total_debt - safe_row("Cash & Equivalents")
    if "Net Income" in df.index and "Total Equity" in df.index:
        eq = df.loc["Total Equity"].replace(0, float("nan"))
        df.loc["ROE %"] = df.loc["Net Income"] / eq * 100
    if "Net Income" in df.index and "Total Assets" in df.index:
        ta = df.loc["Total Assets"].replace(0, float("nan"))
        df.loc["ROA %"] = df.loc["Net Income"] / ta * 100
    if "Gross Profit" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Gross Margin %"] = df.loc["Gross Profit"] / rev * 100
    if "Operating Income" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Operating Margin %"] = df.loc["Operating Income"] / rev * 100
    if "Net Income" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["Net Margin %"] = df.loc["Net Income"] / rev * 100
    if "Free Cash Flow" in df.index and "Revenue" in df.index:
        rev = df.loc["Revenue"].replace(0, float("nan"))
        df.loc["FCF Margin %"] = df.loc["Free Cash Flow"] / rev * 100
    if "Total Equity" in df.index:
        total_debt = safe_row("Long-Term Debt") + safe_row("Short-Term Debt")
        eq = df.loc["Total Equity"].replace(0, float("nan"))
        df.loc["Debt/Equity"] = total_debt / eq
    return df

RATIO_LABELS = {"ROE %","ROA %","Gross Margin %","Operating Margin %","Net Margin %","FCF Margin %","Debt/Equity",
                "10-Year Avg ROE %","5-Year Avg Pretax Income","Earnings Yield %",
                "P/B Ratio","P/S Ratio","P/E Ratio","P/FCF Ratio","EV/EBITDA"}

@st.cache_data(ttl=3600, show_spinner=False)
def compute_10yr_roe(ticker):
    """Returns (avg_roe, {year: roe_pct}) using SEC EDGAR 10-K data (up to 10 years)."""
    cik = get_cik(ticker)
    if not cik:
        return None, {}
    try:
        facts = get_edgar_facts(cik)
        df = extract_edgar_annual(facts, {**EDGAR_INCOME, **EDGAR_BALANCE})
        if df.empty or "Net Income" not in df.index or "Total Equity" not in df.index:
            return None, {}
        ni  = df.loc["Net Income"]
        eq  = df.loc["Total Equity"].replace(0, float("nan"))
        roe = (ni / eq * 100).dropna()
        years = sorted(roe.index, reverse=True)[:10]
        year_data = {y: round(float(roe[y]), 2) for y in sorted(years)}
        avg = round(float(roe[list(years)].mean()), 2)
        return avg, year_data
    except Exception:
        return None, {}

def _is_10yr_roe_query(question):
    q = question.lower()
    has_10  = "10" in q or "ten year" in q or "decade" in q
    has_roe = "roe" in q or "return on equity" in q
    return has_10 and has_roe

@st.cache_data(ttl=3600, show_spinner=False)
def compute_5yr_pretax_income(ticker):
    """Returns (avg, {year: pretax_income}) from SEC EDGAR 10-K data (up to 5 years)."""
    cik = get_cik(ticker)
    if not cik:
        return None, {}
    try:
        facts = get_edgar_facts(cik)
        df = extract_edgar_annual(facts, EDGAR_INCOME)
        if df.empty or "Pretax Income" not in df.index:
            return None, {}
        row = df.loc["Pretax Income"].dropna()
        years = sorted(row.index, reverse=True)[:5]
        year_data = {y: float(row[y]) for y in sorted(years)}
        avg = float(row[list(years)].mean())
        return avg, year_data
    except Exception:
        return None, {}

def _is_5yr_pretax_query(question):
    q = question.lower()
    has_5      = "5" in q or "five year" in q
    has_pretax = "pretax" in q or "pre-tax" in q or "pre tax" in q
    has_income = "income" in q or "net income" in q or "earnings" in q or "profit" in q
    return has_5 and has_pretax and has_income

@st.cache_data(ttl=120, show_spinner=False)
def compute_earnings_yield(ticker):
    """Returns (earnings_yield_pct, eps, price) using most recent EDGAR EPS and current price."""
    try:
        price_data = fetch_price_data(ticker)
        price = price_data.get("currentPrice")
        if not price or price <= 0:
            return None, None, None
        cik = get_cik(ticker)
        if not cik:
            return None, None, None
        facts = get_edgar_facts(cik)
        df = extract_edgar_annual(facts, EDGAR_INCOME)
        if df.empty or "EPS Diluted" not in df.index:
            return None, None, None
        row = df.loc["EPS Diluted"].dropna()
        if row.empty:
            return None, None, None
        eps = float(row[max(row.index)])
        earnings_yield = (eps / price) * 100
        return round(earnings_yield, 4), round(eps, 2), round(price, 2)
    except Exception:
        return None, None, None

def _is_earnings_yield_query(question):
    q = question.lower()
    return "earnings yield" in q or "earning yield" in q or "eps yield" in q or (("e/p" in q) and ("ratio" in q or "yield" in q))

@st.cache_data(ttl=120, show_spinner=False)
def compute_valuation_ratios(ticker):
    """
    Returns a dict of valuation ratios using EDGAR fundamentals + live price.
    Ratios: P/E, P/B, P/S, P/FCF, EV/EBITDA, Market Cap, Enterprise Value.
    """
    try:
        price_data = fetch_price_data(ticker)
        price = price_data.get("currentPrice")
        if not price or price <= 0:
            return {}

        cik = get_cik(ticker)
        if not cik:
            return {}
        facts = get_edgar_facts(cik)
        inc = extract_edgar_annual(facts, EDGAR_INCOME)
        bal = extract_edgar_annual(facts, EDGAR_BALANCE)
        cf_map = {k: v for k, v in EDGAR_CASHFLOW.items() if v}
        cf  = extract_edgar_annual(facts, cf_map)

        def latest(df, label):
            if df.empty or label not in df.index:
                return None
            row = df.loc[label].dropna()
            return float(row[max(row.index)]) if not row.empty else None

        eps        = latest(inc, "EPS Diluted")
        revenue    = latest(inc, "Revenue")
        net_income = latest(inc, "Net Income")
        op_income  = latest(inc, "Operating Income")
        da         = latest(inc, "Depreciation & Amort")
        shares     = latest(inc, "Shares Outstanding")
        equity     = latest(bal, "Total Equity")
        cash       = latest(bal, "Cash & Equivalents")
        lt_debt    = latest(bal, "Long-Term Debt") or 0
        st_debt    = latest(bal, "Short-Term Debt") or 0
        op_cf      = latest(cf,  "Operating Cash Flow")
        capex      = latest(cf,  "Capital Expenditures")

        ratios = {}

        # Market Cap
        if shares:
            mkt_cap = price * shares
            ratios["Market Cap"] = mkt_cap
        else:
            mkt_cap = None

        # P/E
        if eps and eps > 0:
            ratios["P/E Ratio"] = round(price / eps, 2)

        # P/B
        if shares and equity and equity > 0:
            bvps = equity / shares
            ratios["P/B Ratio"] = round(price / bvps, 2)

        # P/S
        if shares and revenue and revenue > 0:
            ratios["P/S Ratio"] = round((price * shares) / revenue, 2)

        # P/FCF
        if shares and op_cf is not None and capex is not None:
            fcf = op_cf - abs(capex)
            if fcf > 0:
                ratios["P/FCF Ratio"] = round((price * shares) / fcf, 2)

        # EV/EBITDA
        if mkt_cap is not None:
            total_debt = lt_debt + st_debt
            ev = mkt_cap + total_debt - (cash or 0)
            ratios["Enterprise Value"] = ev
            ebitda = None
            if op_income is not None and da is not None:
                ebitda = op_income + abs(da)
            elif op_income is not None:
                ebitda = op_income
            if ebitda and ebitda > 0:
                ratios["EV/EBITDA"] = round(ev / ebitda, 2)

        return ratios
    except Exception:
        return {}

def _valuation_ratio_requested(question):
    """
    Returns the specific ratio name if the question asks for a valuation ratio, else None.
    Uses word-presence checks rather than exact substrings so natural phrasing always matches.
    """
    q = question.lower()
    has = lambda *words: all(w in q for w in words)
    has_any = lambda *phrases: any(p in q for p in phrases)

    # EV/EBITDA — check before "enterprise value" alone
    if has_any("ev/ebitda", "ev ebitda") or (has("enterprise", "ebitda")):
        return "EV/EBITDA"

    # Enterprise Value (without EBITDA)
    if has("enterprise", "value") and "ebitda" not in q:
        return "Enterprise Value"

    # Market Cap
    if has_any("market cap", "market capitalization") or has("market", "cap") or has("market", "value"):
        return "Market Cap"

    # P/B — price + book (any phrasing)
    if has_any("p/b", "pb ratio") or (has("price", "book")) or has("book", "value", "ratio"):
        return "P/B Ratio"

    # P/FCF — check before P/S so "free cash flow" doesn't fall into sales
    if has_any("p/fcf", "price/fcf") or has("price", "free", "cash"):
        return "P/FCF Ratio"

    # P/S — price + sales or revenue
    if has_any("p/s", "ps ratio") or has("price", "sales") or has("price", "revenue"):
        return "P/S Ratio"

    # P/E — price + earnings (guard against matching "price book" already caught above)
    if has_any("p/e", "pe ratio") or has("price", "earnings") or has("price", "earning"):
        return "P/E Ratio"

    return None

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

# ── Data fetchers ─────────────────────────────────────────────────────────────
# yf.download() uses a different Yahoo Finance endpoint that does NOT require
# cookie/crumb auth — it works reliably on cloud. We use it for all price data.
# SEC EDGAR (already in use for financial search) handles financial statements.
# yf.Ticker().info is AVOIDED — that's the endpoint Yahoo blocks on cloud IPs.

@st.cache_data(ttl=120, show_spinner=False)
def fetch_price_data(ticker):
    """Current price + basic stats via yf.download() — works on cloud."""
    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            return {}
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        return {
            "currentPrice":   float(last["Close"]),
            "previousClose":  float(prev["Close"]),
            "dayHigh":        float(last["High"]),
            "dayLow":         float(last["Low"]),
            "volume":         int(last["Volume"]),
            "open":           float(last["Open"]),
        }
    except Exception:
        return {}

@st.cache_data(ttl=120, show_spinner=False)
def fetch_history(ticker, period="1y", interval="1d"):
    """Price history via yf.download() — works on cloud."""
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_company_meta(ticker):
    """Name, sector, industry from SEC EDGAR — no Yahoo auth needed."""
    try:
        companies = get_company_list()
        name = next((n for s, n in companies if s == ticker.upper()), ticker)
        cik  = get_cik(ticker)
        sector, industry, website = "", "", ""
        if cik:
            r = requests.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers=EDGAR_HEADERS, timeout=10
            )
            if r.ok:
                d = r.json()
                name    = d.get("name", name)
                sic_desc= d.get("sicDescription", "")
                website = d.get("website", "")
                sector  = sic_desc
        return {"name": name, "sector": sector, "industry": industry, "website": website, "cik": cik}
    except Exception:
        companies = get_company_list()
        name = next((n for s, n in companies if s == ticker.upper()), ticker)
        return {"name": name, "sector": "", "industry": "", "website": "", "cik": None}

@st.cache_data(ttl=900, show_spinner=False)
def fetch_news(ticker):
    """News headlines via Yahoo RSS — no auth needed."""
    try:
        url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        articles = []
        for item in root.findall(".//item")[:8]:
            title = item.findtext("title", "")
            link  = item.findtext("link", "")
            pub   = item.findtext("pubDate", "")
            try:
                dt_str = pd.to_datetime(pub).strftime("%b %d  %H:%M")
            except Exception:
                dt_str = ""
            if title:
                articles.append({"title": title, "url": link, "source": "Yahoo Finance", "time": dt_str})
        return articles
    except Exception:
        return []

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"], .main, .stApp {
        background-color: #ffffff;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    .block-container { padding-top: 2.5rem !important; padding-bottom: 2rem; max-width: 1200px; }
    section[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e2e8f0; }
    header[data-testid="stHeader"] { background: #ffffff !important; border-bottom: 1px solid #e2e8f0; }

    [data-testid="stStatusWidget"] { display: none !important; }

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
    button[kind="secondary"] {
        color: #3d5a7a !important; background: #f8fafc !important;
        border: 1px solid #dde6f0 !important; font-family: 'Inter', sans-serif !important;
    }
    button[kind="secondary"]:hover {
        color: #2563eb !important; background: #eff6ff !important; border-color: #93c5fd !important;
    }
    [data-testid="stDialog"] > div,
    [data-testid="stDialog"] [data-testid="stVerticalBlock"] {
        background-color: #ffffff !important;
    }
    [data-testid="stDialog"] { background: rgba(30,58,92,0.18) !important; }
</style>
""", unsafe_allow_html=True)

# Pre-warm company list
if "companies_loaded" not in st.session_state:
    get_company_list()
    st.session_state.companies_loaded = True

# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="display:flex; align-items:center; padding:8px 0 6px; border-bottom:1px solid #e2e8f0; margin-bottom:24px;">
    <div>
        <span style="color:#1e3a5c; font-size:24px; font-weight:800; letter-spacing:-0.5px;">Finance Tools</span>
        <span style="color:#94a3b8; font-size:13px; margin-left:12px;">Financial Data Search &amp; Company Profiles</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL DATA SEARCH
# ══════════════════════════════════════════════════════════════════════════════
st.markdown('<div class="section-header">Financial Data Search</div>', unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; font-size:12px; margin:-8px 0 12px;'>Ask any question about a company's financials. Data goes back to early 2000s via SEC EDGAR.</p>", unsafe_allow_html=True)

with st.form("financial_search_form"):
    ai_question = st.text_input(
        "Financial question",
        placeholder='e.g. "AAPL net income 2023" or "What was Microsoft\'s depreciation in 2016?"',
        label_visibility="collapsed",
    )
    search_btn = st.form_submit_button("Search", use_container_width=True)

st.markdown("<p style='color:#94a3b8; font-size:11px; margin-top:4px;'>Try: &nbsp; MSFT depreciation 2016 &nbsp;·&nbsp; AAPL interest expense 2019 &nbsp;·&nbsp; OXY pretax income 2023 &nbsp;·&nbsp; NVDA EBITDA 2022</p>", unsafe_allow_html=True)

if ai_question and search_btn:
    search_ticker, s_name = extract_ticker_from_question(ai_question, None)
    if not search_ticker:
        st.info("Couldn't identify the company. Include the ticker or company name in your question — e.g. 'AAPL revenue 2023' or 'Apple net income 2022'.")
    else:
        with st.spinner(f"Searching {s_name or search_ticker}…"):
            try:
                if not s_name or s_name == search_ticker:
                    try:
                        meta = fetch_company_meta(search_ticker)
                        s_name = meta.get("name") or search_ticker
                    except Exception:
                        s_name = search_ticker
                # ── Valuation ratios — special path ───────────────────────
                _requested_ratio = _valuation_ratio_requested(ai_question)
                if _requested_ratio:
                    ratios = compute_valuation_ratios(search_ticker)
                    val = ratios.get(_requested_ratio)
                    if val is not None:
                        if _requested_ratio in ("Market Cap", "Enterprise Value"):
                            fv = fmt_large(val)
                            suffix = ""
                        else:
                            fv = f"{val:.2f}x"
                            suffix = "x"
                        st.markdown(f"""
                        <div class="answer-box">
                            <div class="answer-label">{s_name} ({search_ticker}) · SEC EDGAR 10-K + Live Price</div>
                            <div class="answer-item">{_requested_ratio}</div>
                            <div class="answer-value">{fv}</div>
                            <div class="answer-meta">Based on most recent annual filing &amp; current market price</div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.info(f"{_requested_ratio} not available for {s_name} ({search_ticker}) — insufficient EDGAR data.")

                # ── Earnings Yield — special path ─────────────────────────
                elif _is_earnings_yield_query(ai_question):
                    ey, eps, price = compute_earnings_yield(search_ticker)
                    if ey is not None:
                        ey_color = "#16a34a" if ey >= 0 else "#dc2626"
                        ey_sign  = "+" if ey >= 0 else ""
                        pe_str   = f"{1/(ey/100):.1f}x" if ey != 0 else "N/A"
                        st.markdown(f"""
                        <div class="answer-box">
                            <div class="answer-label">{s_name} ({search_ticker}) · SEC EDGAR 10-K + Live Price</div>
                            <div class="answer-item">Earnings Yield (EPS ÷ Price)</div>
                            <div class="answer-value" style="color:{ey_color};">{ey_sign}{ey:.2f}%</div>
                            <div class="answer-meta">EPS (diluted): ${eps:.2f} &nbsp;·&nbsp; Price: ${price:,.2f} &nbsp;·&nbsp; Implied P/E: {pe_str}</div>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.info(f"Earnings yield data not available for {s_name} ({search_ticker}) — EPS or price data missing.")

                # ── 5-Year Avg Pretax Income — special path ───────────────
                elif _is_5yr_pretax_query(ai_question):
                    avg_pt, pt_by_year = compute_5yr_pretax_income(search_ticker)
                    if avg_pt is not None and pt_by_year:
                        avg_color = "#16a34a" if avg_pt >= 0 else "#dc2626"
                        avg_sign  = "+" if avg_pt >= 0 else ""
                        yrs = sorted(pt_by_year.keys())
                        rows_html = "".join(
                            f"<tr><td style='padding:5px 12px;color:#64748b;'>{y}</td>"
                            f"<td style='padding:5px 12px;text-align:right;"
                            f"color:{'#16a34a' if pt_by_year[y]>=0 else '#dc2626'};font-weight:600;'>"
                            f"{fmt_large(pt_by_year[y])}</td></tr>"
                            for y in sorted(yrs, reverse=True)
                        )
                        st.markdown(f"""
                        <div class="answer-box">
                            <div class="answer-label">{s_name} ({search_ticker}) · SEC EDGAR 10-K</div>
                            <div class="answer-item">5-Year Average Pretax Net Income ({yrs[0]}–{yrs[-1]})</div>
                            <div class="answer-value" style="color:{avg_color};">{avg_sign}{fmt_large(avg_pt)}</div>
                            <div class="answer-meta">{len(yrs)} fiscal years averaged</div>
                        </div>""", unsafe_allow_html=True)
                        with st.expander("Year-by-year breakdown"):
                            st.markdown(
                                f'<table style="width:100%;font-family:Inter,sans-serif;font-size:12px;">'
                                f'<thead><tr>'
                                f'<th style="text-align:left;padding:5px 12px;color:#94a3b8;font-size:10px;text-transform:uppercase;">Year</th>'
                                f'<th style="text-align:right;padding:5px 12px;color:#94a3b8;font-size:10px;text-transform:uppercase;">Pretax Income</th>'
                                f'</tr></thead><tbody>{rows_html}</tbody></table>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.info(f"5-year pretax income data not available for {s_name} ({search_ticker}) — SEC EDGAR may not have sufficient history.")

                # ── 10-Year ROE — special path ─────────────────────────────
                elif _is_10yr_roe_query(ai_question):
                    avg_roe, year_data = compute_10yr_roe(search_ticker)
                    if avg_roe is not None and year_data:
                        sign = "+" if avg_roe >= 0 else ""
                        color = "#16a34a" if avg_roe >= 0 else "#dc2626"
                        yrs   = sorted(year_data.keys())
                        n_yrs = len(yrs)
                        rows_html = "".join(
                            f"<tr><td style='padding:5px 12px;color:#64748b;'>{y}</td>"
                            f"<td style='padding:5px 12px;text-align:right;"
                            f"color:{'#16a34a' if year_data[y]>=0 else '#dc2626'};font-weight:600;'>"
                            f"{'+' if year_data[y]>=0 else ''}{year_data[y]:.2f}%</td></tr>"
                            for y in sorted(yrs, reverse=True)
                        )
                        st.markdown(f"""
                        <div class="answer-box">
                            <div class="answer-label">{s_name} ({search_ticker}) · SEC EDGAR 10-K</div>
                            <div class="answer-item">10-Year Average ROE ({yrs[0]}–{yrs[-1]})</div>
                            <div class="answer-value" style="color:{color};">{sign}{avg_roe:.2f}%</div>
                            <div class="answer-meta">{n_yrs} fiscal years averaged</div>
                        </div>""", unsafe_allow_html=True)
                        with st.expander("Year-by-year breakdown"):
                            st.markdown(
                                f'<table style="width:100%;font-family:Inter,sans-serif;font-size:12px;">'
                                f'<thead><tr>'
                                f'<th style="text-align:left;padding:5px 12px;color:#94a3b8;font-size:10px;text-transform:uppercase;">Year</th>'
                                f'<th style="text-align:right;padding:5px 12px;color:#94a3b8;font-size:10px;text-transform:uppercase;">ROE %</th>'
                                f'</tr></thead><tbody>{rows_html}</tbody></table>',
                                unsafe_allow_html=True,
                            )
                    else:
                        st.info(f"10-year ROE data not available for {s_name} ({search_ticker}) — SEC EDGAR may not have sufficient history.")
                else:
                # ── Normal search path ─────────────────────────────────────────
                    result = None
                    try:
                        result = search_edgar(ai_question, search_ticker)
                    except Exception:
                        pass
                    if not result:
                        try:
                            result = search_yfinance(ai_question, yf.Ticker(search_ticker, session=None))
                        except Exception:
                            pass
                    if result:
                        val, item, period, source = result
                        try:
                            period_label = f"Fiscal Year {period}" if isinstance(period, int) else pd.to_datetime(str(period)).strftime("%b %d, %Y")
                        except Exception:
                            period_label = str(period)
                        if item in RATIO_LABELS:
                            fv = f"{val:.2f}%" if "%" in item else f"{val:.2f}x"
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
                        <div style="background:#fff7ed;border:1px solid #fed7aa;border-left:3px solid #f97316;border-radius:6px;padding:16px 20px;margin:10px 0;">
                            <div style="color:#c2410c;font-size:13px;font-weight:600;">Metric not found for {s_name} ({search_ticker})</div>
                            <div style="color:#64748b;font-size:12px;margin-top:6px;">
                                This metric may not be reported by this company, or try rephrasing.<br>
                                <span style="color:#64748b;">Examples: &nbsp;
                                <b style="color:#94a3b8;">revenue · net income · EBITDA · free cash flow · total debt · net debt · ROE · gross margin · pretax income · capex</b>
                                </span>
                            </div>
                        </div>""", unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Error: {e}")

st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY PROFILE LOOKUP
# ══════════════════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════════════════
# DCF / INTRINSIC VALUE CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)
st.markdown('<div class="section-header">DCF Intrinsic Value Calculator</div>', unsafe_allow_html=True)
st.markdown(
    "<p style='color:#64748b; font-size:12px; margin:-8px 0 12px;'>"
    "Discounted cash flow model using SEC EDGAR free cash flow data. "
    "Adjust growth and discount assumptions to stress-test valuations.</p>",
    unsafe_allow_html=True,
)

with st.form("dcf_ticker_form"):
    dcf_query = st.text_input(
        "Ticker or company name",
        placeholder="e.g. AAPL, Microsoft, NVDA…",
        label_visibility="collapsed",
        key="dcf_query",
    )
    dcf_load_btn = st.form_submit_button("Load Company", use_container_width=True)

if dcf_load_btn and dcf_query:
    q = dcf_query.strip()
    override = NAME_OVERRIDES.get(q.lower())
    if override:
        st.session_state["dcf_ticker"] = override
    else:
        result = resolve_company_ticker(q)
        st.session_state["dcf_ticker"] = result[0] if result else q.upper()

dcf_ticker = st.session_state.get("dcf_ticker")

if dcf_ticker:
    with st.spinner(f"Loading {dcf_ticker} fundamentals from SEC EDGAR…"):
        try:
            cik = get_cik(dcf_ticker)
            if not cik:
                st.error(f"No SEC EDGAR data found for **{dcf_ticker}**. Check the ticker symbol.")
            else:
                facts  = get_edgar_facts(cik)
                cf_map = {k: v for k, v in EDGAR_CASHFLOW.items() if v}
                df_cf  = extract_edgar_annual(facts, cf_map)
                df_inc = extract_edgar_annual(facts, EDGAR_INCOME)

                # Build FCF series from EDGAR
                fcf_by_year = {}
                if (not df_cf.empty
                        and "Operating Cash Flow" in df_cf.index
                        and "Capital Expenditures" in df_cf.index):
                    ocf   = df_cf.loc["Operating Cash Flow"].dropna()
                    capex = df_cf.loc["Capital Expenditures"].dropna().abs()
                    for y in sorted(set(ocf.index) & set(capex.index), reverse=True):
                        fcf_by_year[y] = float(ocf[y]) - float(capex[y])

                if not fcf_by_year:
                    st.warning(f"Free cash flow data not available for **{dcf_ticker}** on EDGAR. "
                               "The company may not file 10-Ks or may have incomplete cash flow data.")
                else:
                    recent_years = sorted(fcf_by_year, reverse=True)[:3]
                    base_fcf_avg = sum(fcf_by_year[y] for y in recent_years) / len(recent_years)
                    latest_fcf   = fcf_by_year[recent_years[0]]
                    latest_year  = recent_years[0]

                    # Shares outstanding
                    shares = None
                    if not df_inc.empty and "Shares Outstanding" in df_inc.index:
                        sr = df_inc.loc["Shares Outstanding"].dropna()
                        if not sr.empty:
                            shares = float(sr[max(sr.index)])

                    # Current price
                    price_data    = fetch_price_data(dcf_ticker)
                    current_price = price_data.get("currentPrice")

                    companies = get_company_list()
                    dcf_name  = next((n for s, n in companies if s == dcf_ticker), dcf_ticker)

                    # ── Company summary bar ────────────────────────────────────
                    summary_items = [
                        f'<span style="color:#94a3b8;font-size:12px;">Current Price &nbsp;<b style="color:#1e3a5c;">${current_price:,.2f}</b></span>'
                        if current_price else "",
                        f'<span style="color:#94a3b8;font-size:12px;">Latest FCF ({latest_year}) &nbsp;<b style="color:#1e3a5c;">{fmt_large(latest_fcf)}</b></span>',
                        f'<span style="color:#94a3b8;font-size:12px;">3-Year Avg FCF &nbsp;<b style="color:#1e3a5c;">{fmt_large(base_fcf_avg)}</b></span>',
                        f'<span style="color:#94a3b8;font-size:12px;">Shares Out &nbsp;<b style="color:#1e3a5c;">{fmt_large(shares)}</b></span>'
                        if shares else "",
                    ]
                    st.markdown(
                        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
                        f'padding:16px 22px;margin-bottom:20px;">'
                        f'<div style="color:#1e3a5c;font-size:18px;font-weight:700;margin-bottom:8px;">'
                        f'{dcf_name} &nbsp;<span style="color:#94a3b8;font-size:14px;font-weight:400;">({dcf_ticker})</span></div>'
                        f'<div style="display:flex;gap:24px;flex-wrap:wrap;">'
                        + "".join(summary_items) +
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )

                    # ── Assumption sliders ─────────────────────────────────────
                    st.markdown(
                        "<p style='color:#94a3b8;font-size:10px;font-weight:600;text-transform:uppercase;"
                        "letter-spacing:.12em;margin-bottom:10px;'>Model Assumptions</p>",
                        unsafe_allow_html=True,
                    )
                    sl1, sl2 = st.columns(2)
                    with sl1:
                        growth_1   = st.slider("Stage 1 growth — years 1–5",  -10, 50, 10, step=1, format="%d%%", key="dcf_g1",
                                               help="Annual FCF growth rate for the first 5 years.")
                        terminal_g = st.slider("Terminal growth rate",           0,  5,  2, step=1, format="%d%%", key="dcf_tg",
                                               help="Perpetual growth beyond year 10. Usually close to long-run GDP (~2–3%).")
                    with sl2:
                        growth_2 = st.slider("Stage 2 growth — years 6–10", -10, 30,  5, step=1, format="%d%%", key="dcf_g2",
                                             help="Annual FCF growth rate for years 6–10 (fade period).")
                        wacc     = st.slider("Discount rate (WACC)",           5, 20, 10, step=1, format="%d%%", key="dcf_wacc",
                                             help="Required rate of return. Higher = more conservative. 8–12% is typical for equities.")

                    base_label = st.radio(
                        "Starting FCF",
                        [f"3-Year Average  ({fmt_large(base_fcf_avg)})", f"Latest year {latest_year}  ({fmt_large(latest_fcf)})"],
                        horizontal=True,
                        label_visibility="collapsed",
                        key="dcf_base",
                    )
                    starting_fcf = base_fcf_avg if "Average" in base_label else latest_fcf

                    # ── DCF model ──────────────────────────────────────────────
                    g1 = growth_1   / 100
                    g2 = growth_2   / 100
                    tg = terminal_g / 100
                    r  = wacc       / 100

                    proj_fcfs, pv_fcfs = [], []
                    fcf_t = starting_fcf
                    for t in range(1, 11):
                        fcf_t = fcf_t * (1 + (g1 if t <= 5 else g2))
                        proj_fcfs.append(fcf_t)
                        pv_fcfs.append(fcf_t / (1 + r) ** t)

                    if r > tg:
                        tv_pv = (proj_fcfs[-1] * (1 + tg) / (r - tg)) / (1 + r) ** 10
                    else:
                        tv_pv = 0

                    total_pv            = sum(pv_fcfs) + tv_pv
                    intrinsic_per_share = total_pv / shares if shares and shares > 0 else None
                    mos = ((intrinsic_per_share - current_price) / current_price * 100
                           if intrinsic_per_share and current_price and current_price > 0 else None)

                    # ── Result cards ───────────────────────────────────────────
                    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
                    rc1, rc2, rc3, rc4 = st.columns(4)

                    with rc1:
                        iv_str = f"${intrinsic_per_share:,.2f}" if intrinsic_per_share else "N/A — no share count"
                        st.markdown(
                            f'<div class="metric-card">'
                            f'<div class="metric-label">Intrinsic Value / Share</div>'
                            f'<div class="metric-value" style="font-size:22px;">{iv_str}</div>'
                            f'</div>', unsafe_allow_html=True,
                        )
                    with rc2:
                        cp_str = f"${current_price:,.2f}" if current_price else "N/A"
                        st.markdown(
                            f'<div class="metric-card">'
                            f'<div class="metric-label">Current Price</div>'
                            f'<div class="metric-value" style="font-size:22px;">{cp_str}</div>'
                            f'</div>', unsafe_allow_html=True,
                        )
                    with rc3:
                        if mos is not None:
                            mos_color = "#16a34a" if mos > 0 else "#dc2626"
                            mos_lbl   = "Margin of Safety" if mos > 0 else "Premium to Value"
                            mos_str   = f'{"+" if mos > 0 else ""}{mos:.1f}%'
                        else:
                            mos_color, mos_lbl, mos_str = "#94a3b8", "Margin of Safety", "N/A"
                        st.markdown(
                            f'<div class="metric-card">'
                            f'<div class="metric-label">{mos_lbl}</div>'
                            f'<div class="metric-value" style="font-size:22px;color:{mos_color};">{mos_str}</div>'
                            f'</div>', unsafe_allow_html=True,
                        )
                    with rc4:
                        st.markdown(
                            f'<div class="metric-card">'
                            f'<div class="metric-label">Enterprise Value (PV)</div>'
                            f'<div class="metric-value" style="font-size:22px;">{fmt_large(total_pv)}</div>'
                            f'</div>', unsafe_allow_html=True,
                        )

                    # PV breakdown
                    pv_s1  = sum(pv_fcfs[:5])
                    pv_s2  = sum(pv_fcfs[5:])
                    bd1, bd2, bd3 = st.columns(3)
                    for col, lbl, val in [
                        (bd1, "PV Stage 1 (yrs 1–5)",  pv_s1),
                        (bd2, "PV Stage 2 (yrs 6–10)", pv_s2),
                        (bd3, "PV Terminal Value",      tv_pv),
                    ]:
                        pct = val / total_pv * 100 if total_pv else 0
                        col.markdown(
                            f'<div class="metric-card">'
                            f'<div class="metric-label">{lbl}</div>'
                            f'<div class="metric-value">{fmt_large(val)} '
                            f'<span style="color:#94a3b8;font-size:12px;">({pct:.0f}%)</span></div>'
                            f'</div>', unsafe_allow_html=True,
                        )

                    # ── Projection chart ───────────────────────────────────────
                    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
                    yr_labels = [str(latest_year + t) for t in range(1, 11)]
                    fig_dcf = go.Figure()
                    fig_dcf.add_trace(go.Bar(
                        x=yr_labels,
                        y=[v / 1e9 for v in proj_fcfs],
                        name="Projected FCF",
                        marker_color=["#2563eb"] * 5 + ["#7c3aed"] * 5,
                        hovertemplate="<b>%{x}</b><br>FCF: $%{y:.2f}B<extra></extra>",
                    ))
                    fig_dcf.add_trace(go.Bar(
                        x=yr_labels,
                        y=[v / 1e9 for v in pv_fcfs],
                        name="Present Value",
                        marker_color=["#93c5fd"] * 5 + ["#c4b5fd"] * 5,
                        hovertemplate="<b>%{x}</b><br>PV: $%{y:.2f}B<extra></extra>",
                    ))
                    fig_dcf.update_layout(
                        paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
                        margin=dict(l=10, r=10, t=36, b=10), height=250,
                        barmode="group",
                        title=dict(text="Projected FCF vs Present Value  (Stage 1 = blue · Stage 2 = purple)",
                                   font=dict(size=11, color="#64748b"), x=0),
                        xaxis=dict(showgrid=False, tickfont=dict(size=11, color="#64748b")),
                        yaxis=dict(showgrid=True, gridcolor="#e2e8f0",
                                   tickfont=dict(size=11, color="#64748b"),
                                   ticksuffix="B",
                                   title=dict(text="USD Billions", font=dict(size=11, color="#94a3b8"))),
                        legend=dict(bgcolor="#ffffff", font=dict(size=11, color="#475569"),
                                    orientation="h", x=0, y=1.12),
                    )
                    st.plotly_chart(fig_dcf, width="stretch")

                    # ── Historical FCF table ───────────────────────────────────
                    with st.expander("Historical Free Cash Flow (EDGAR 10-K)"):
                        hist_rows = "".join(
                            f'<tr><td style="padding:6px 14px;color:#64748b;">{y}</td>'
                            f'<td style="padding:6px 14px;text-align:right;font-weight:600;'
                            f'color:{"#16a34a" if fcf_by_year[y] >= 0 else "#dc2626"};">'
                            f'{fmt_large(fcf_by_year[y])}</td></tr>'
                            for y in sorted(fcf_by_year, reverse=True)
                        )
                        st.markdown(
                            f'<div style="overflow-x:auto;border-radius:7px;border:1px solid #e2e8f0;">'
                            f'<table style="width:100%;border-collapse:collapse;font-family:Inter,sans-serif;font-size:12px;">'
                            f'<thead><tr>'
                            f'<th style="padding:7px 14px;color:#94a3b8;text-align:left;font-size:10px;'
                            f'text-transform:uppercase;background:#f1f5f9;border-bottom:1px solid #e2e8f0;">Fiscal Year</th>'
                            f'<th style="padding:7px 14px;color:#94a3b8;text-align:right;font-size:10px;'
                            f'text-transform:uppercase;background:#f1f5f9;border-bottom:1px solid #e2e8f0;">Free Cash Flow</th>'
                            f'</tr></thead><tbody>{hist_rows}</tbody></table></div>',
                            unsafe_allow_html=True,
                        )

                    st.markdown(
                        "<p style='color:#94a3b8;font-size:10.5px;margin-top:10px;line-height:1.6;'>"
                        "<b>Methodology:</b> 2-stage DCF — Stage 1 projects FCF at the specified growth rate "
                        "for years 1–5, Stage 2 fades to the second rate for years 6–10, then a Gordon Growth "
                        "terminal value is applied. All future cash flows are discounted at the WACC. "
                        "Intrinsic value per share = total PV ÷ shares outstanding (from EDGAR). "
                        "This is for educational purposes only and is not investment advice.</p>",
                        unsafe_allow_html=True,
                    )

        except Exception as _dcf_err:
            st.error(f"Error running DCF for {dcf_ticker}: {_dcf_err}")

# ══════════════════════════════════════════════════════════════════════════════
# COMPANY PROFILE DIALOG
# ══════════════════════════════════════════════════════════════════════════════
@st.dialog("Company Profile", width="large")
def show_profile(ticker):
    with st.spinner(f"Loading {ticker}…"):
        # ── All data via cloud-safe endpoints (no Yahoo auth required) ──────────
        price_data = fetch_price_data(ticker)
        meta       = fetch_company_meta(ticker)

        if not price_data:
            st.error(f"No price data found for **{ticker}**. Check the ticker symbol.")
            return

        name     = meta.get("name", ticker)
        sector   = meta.get("sector", "")
        website  = meta.get("website", "")
        cik      = meta.get("cik")

        price      = price_data.get("currentPrice", 0)
        prev_close = price_data.get("previousClose", 0)
        day_high   = price_data.get("dayHigh")
        day_low    = price_data.get("dayLow")
        volume     = price_data.get("volume")
        chg        = price - prev_close if price and prev_close else 0
        pct_chg    = chg / prev_close * 100 if prev_close else 0
        sign       = "+" if chg >= 0 else ""
        clr        = "#22c55e" if chg >= 0 else "#ef4444"
        arr        = "▲" if chg >= 0 else "▼"
        range_str  = f"${day_low:,.2f} – ${day_high:,.2f}" if day_low and day_high else "—"

        website_html = (
            f'<a href="{website}" target="_blank" style="color:#2563eb;font-size:12px;">'
            f'{website.replace("https://","").replace("http://","").rstrip("/")}</a>'
        ) if website else ""

        # Header
        st.markdown(
            f'<div style="background:#f8fafc;border:none;border-bottom:2px solid #e2e8f0;'
            f'border-radius:8px 8px 0 0;padding:18px 28px 10px;">'
            f'<div style="color:#1e3a5c;font-size:26px;font-weight:800;line-height:1.2;margin-bottom:4px;">{name}</div>'
            f'<div style="color:#64748b;font-size:12px;letter-spacing:0.02em;">{ticker}'
            + (f'&nbsp;&nbsp;·&nbsp;&nbsp;{sector}' if sector else '') +
            '</div>'
            + (f'<div style="margin-top:4px;">{website_html}</div>' if website_html else '') +
            '</div>',
            unsafe_allow_html=True,
        )

        # Price block
        st.markdown(
            f'<div style="background:#f8fafc;border-radius:0 0 8px 8px;padding:12px 28px 18px;'
            f'border-bottom:2px solid #e2e8f0;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.04);">'
            f'<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;">'
            f'<span style="color:#1e3a5c;font-size:36px;font-weight:800;letter-spacing:-0.5px;line-height:1;">${price:,.2f}</span>'
            f'<span style="color:{clr};font-size:16px;font-weight:700;">{arr} {sign}{chg:,.2f} &nbsp; ({sign}{pct_chg:.2f}%)</span>'
            f'</div>'
            f'<div style="display:flex;gap:20px;margin-top:6px;flex-wrap:wrap;">'
            f'<span style="color:#94a3b8;font-size:11px;">Prev close &nbsp;<b style="color:#64748b;">${prev_close:,.2f}</b></span>'
            f'<span style="color:#94a3b8;font-size:11px;">Day range &nbsp;<b style="color:#64748b;">{range_str}</b></span>'
            + (f'<span style="color:#94a3b8;font-size:11px;">Volume &nbsp;<b style="color:#64748b;">{volume:,}</b></span>' if volume else '') +
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Price chart
        st.markdown('<div class="section-header">Price History</div>', unsafe_allow_html=True)
        PERIOD_CONFIG = {
            "1M":  ("1mo", "1d"),
            "3M":  ("3mo", "1d"),
            "6M":  ("6mo", "1d"),
            "1Y":  ("1y",  "1d"),
            "5Y":  ("5y",  "1wk"),
            "All": ("max", "1mo"),
        }
        period_choice = st.radio("Chart period", list(PERIOD_CONFIG.keys()), horizontal=True, index=3, label_visibility="collapsed")
        yf_period, yf_interval = PERIOD_CONFIG[period_choice]
        hist = fetch_history(ticker, yf_period, yf_interval)
        if not hist.empty:
            lc  = "#22c55e" if hist["Close"].iloc[-1] >= hist["Close"].iloc[0] else "#ef4444"
            rgb = "34,197,94" if lc == "#22c55e" else "239,68,68"
            all_lows  = hist["Low"].dropna()
            all_highs = hist["High"].dropna()
            y_range = None
            if not all_lows.empty and not all_highs.empty:
                y_min   = float(all_lows.min())
                y_max   = float(all_highs.max())
                padding = (y_max - y_min) * 0.15 if y_max > y_min else y_max * 0.01
                y_range = [y_min - padding, y_max + padding]
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
                hovertemplate="<b>%{x|%b %d, %Y}</b><br>$%{y:.2f}<extra></extra>",
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

        # 52-week range from history
        hist_52 = fetch_history(ticker, "1y", "1d")
        w52_high = float(hist_52["High"].max()) if not hist_52.empty else None
        w52_low  = float(hist_52["Low"].min())  if not hist_52.empty else None

        st.markdown('<div class="section-header">Key Statistics</div>', unsafe_allow_html=True)
        ey, ey_eps, ey_price = compute_earnings_yield(ticker)
        c1, c2 = st.columns(2)
        with c1:
            metric_card("52-Wk High", fmt(w52_high, prefix="$"))
            metric_card("52-Wk Low",  fmt(w52_low,  prefix="$"))
            metric_card("Day Range",  range_str if range_str != "—" else None)
        with c2:
            metric_card("Volume",     f"{volume:,}" if volume else "N/A")
            metric_card("Prev Close", fmt(prev_close, prefix="$"))
            if ey is not None:
                ey_sign = "+" if ey >= 0 else ""
                pe_impl = f"  (P/E {1/(ey/100):.1f}x)" if ey != 0 else ""
                metric_card("Earnings Yield", f"{ey_sign}{ey:.2f}%{pe_impl}")

        # 10-Year ROE
        avg_roe, roe_by_year = compute_10yr_roe(ticker)
        if avg_roe is not None and roe_by_year:
            st.markdown('<div class="section-header">10-Year Return on Equity</div>', unsafe_allow_html=True)
            roe_color = "#16a34a" if avg_roe >= 0 else "#dc2626"
            roe_sign  = "+" if avg_roe >= 0 else ""
            yrs = sorted(roe_by_year.keys())
            st.markdown(
                f'<div class="metric-card" style="margin-bottom:12px;">'
                f'<div class="metric-label">10-Year Average ROE ({yrs[0]}–{yrs[-1]})</div>'
                f'<div class="metric-value" style="color:{roe_color};font-size:24px;">{roe_sign}{avg_roe:.2f}%</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # Mini bar chart
            bar_colors = ["#16a34a" if v >= 0 else "#dc2626" for v in roe_by_year.values()]
            fig_roe = go.Figure(go.Bar(
                x=list(roe_by_year.keys()),
                y=list(roe_by_year.values()),
                marker_color=bar_colors,
                hovertemplate="<b>%{x}</b><br>ROE: %{y:.2f}%<extra></extra>",
            ))
            fig_roe.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
                margin=dict(l=10, r=10, t=10, b=10), height=180,
                showlegend=False,
                yaxis=dict(ticksuffix="%", showgrid=True, gridcolor="#e2e8f0",
                           zeroline=True, zerolinecolor="#cbd5e1",
                           tickfont=dict(size=10, color="#64748b")),
                xaxis=dict(tickfont=dict(size=10, color="#64748b"), showgrid=False),
            )
            st.plotly_chart(fig_roe, width="stretch")

        # 5-Year Avg Pretax Income
        avg_pt, pt_by_year = compute_5yr_pretax_income(ticker)
        if avg_pt is not None and pt_by_year:
            st.markdown('<div class="section-header">5-Year Average Pretax Net Income</div>', unsafe_allow_html=True)
            pt_color = "#16a34a" if avg_pt >= 0 else "#dc2626"
            pt_sign  = "+" if avg_pt >= 0 else ""
            yrs_pt   = sorted(pt_by_year.keys())
            st.markdown(
                f'<div class="metric-card" style="margin-bottom:12px;">'
                f'<div class="metric-label">5-Year Average Pretax Income ({yrs_pt[0]}–{yrs_pt[-1]})</div>'
                f'<div class="metric-value" style="color:{pt_color};font-size:24px;">{pt_sign}{fmt_large(avg_pt)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            bar_colors_pt = ["#16a34a" if v >= 0 else "#dc2626" for v in pt_by_year.values()]
            fig_pt = go.Figure(go.Bar(
                x=list(pt_by_year.keys()),
                y=list(pt_by_year.values()),
                marker_color=bar_colors_pt,
                hovertemplate="<b>%{x}</b><br>Pretax Income: $%{y:,.0f}<extra></extra>",
            ))
            fig_pt.update_layout(
                paper_bgcolor="#ffffff", plot_bgcolor="#f8fafc",
                margin=dict(l=10, r=10, t=10, b=10), height=180,
                showlegend=False,
                yaxis=dict(showgrid=True, gridcolor="#e2e8f0",
                           zeroline=True, zerolinecolor="#cbd5e1",
                           tickfont=dict(size=10, color="#64748b"),
                           tickformat="$,.3s"),
                xaxis=dict(tickfont=dict(size=10, color="#64748b"), showgrid=False),
            )
            st.plotly_chart(fig_pt, width="stretch")

        # Valuation Ratios
        val_ratios = compute_valuation_ratios(ticker)
        if val_ratios:
            st.markdown('<div class="section-header">Valuation Ratios</div>', unsafe_allow_html=True)
            RATIO_DISPLAY = [
                ("P/E Ratio",        "Price / Earnings",        "x"),
                ("P/B Ratio",        "Price / Book Value",      "x"),
                ("P/S Ratio",        "Price / Sales",           "x"),
                ("P/FCF Ratio",      "Price / Free Cash Flow",  "x"),
                ("EV/EBITDA",        "EV / EBITDA",             "x"),
                ("Market Cap",       "Market Capitalisation",   "$"),
                ("Enterprise Value", "Enterprise Value",        "$"),
            ]
            v1, v2 = st.columns(2)
            for i, (key, label, unit) in enumerate(RATIO_DISPLAY):
                v = val_ratios.get(key)
                if v is None:
                    continue
                display = fmt_large(v) if unit == "$" else f"{v:.2f}x"
                (v1 if i % 2 == 0 else v2).markdown(
                    f'<div class="metric-card">'
                    f'<div class="metric-label">{label}</div>'
                    f'<div class="metric-value">{display}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        # Financial statements — SEC EDGAR (always works on cloud)
        st.markdown('<div class="section-header">Financial Statements (SEC EDGAR · back to ~2001)</div>', unsafe_allow_html=True)
        if cik:
            try:
                ef = get_edgar_facts(cik)
                df_is_e = extract_edgar_annual(ef, EDGAR_INCOME)
                df_bs_e = extract_edgar_annual(ef, EDGAR_BALANCE)
                cf_map  = {k: v for k, v in EDGAR_CASHFLOW.items() if v}
                df_cf_e = extract_edgar_annual(ef, cf_map)
                if not df_cf_e.empty and "Operating Cash Flow" in df_cf_e.index and "Capital Expenditures" in df_cf_e.index:
                    df_cf_e.loc["Free Cash Flow"] = df_cf_e.loc["Operating Cash Flow"].subtract(df_cf_e.loc["Capital Expenditures"].abs())
                    df_cf_e = df_cf_e.reindex([k for k in EDGAR_CASHFLOW if k in df_cf_e.index])
                h1, h2, h3 = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])
                with h1: render_edgar_table(df_is_e)
                with h2: render_edgar_table(df_bs_e)
                with h3: render_edgar_table(df_cf_e)
            except Exception as e:
                st.markdown(f"<p style='color:#64748b;'>Financial data unavailable: {e}</p>", unsafe_allow_html=True)
        else:
            st.markdown("<p style='color:#64748b;'>SEC EDGAR data not available for this ticker.</p>", unsafe_allow_html=True)

        # News via RSS (no auth)
        st.markdown('<div class="section-header">Company News</div>', unsafe_allow_html=True)
        news = fetch_news(ticker)
        if news:
            for article in news:
                t_html = f'<a href="{article["url"]}" target="_blank">{article["title"]}</a>' if article["url"] else article["title"]
                st.markdown(
                    f'<div class="news-card"><div class="news-title">{t_html}</div>'
                    f'<div class="news-meta">{article["source"]}{"&nbsp;·&nbsp;" if article["time"] else ""}{article["time"]}</div></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown("<p style='color:#64748b;'>No recent news.</p>", unsafe_allow_html=True)

if st.session_state.get("open_ticker"):
    ticker_to_show = st.session_state["open_ticker"]
    st.session_state["open_ticker"] = None
    show_profile(ticker_to_show)
