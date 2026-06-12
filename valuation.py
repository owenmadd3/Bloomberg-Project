"""
Value Screener — 5 valuation methods computed from SEC EDGAR + yFinance.

Each method returns a structured breakdown (symbolic formula + the actual
numbers plugged in + a verdict) so the front-end can show *how* every number
was derived.

Methods:
  1. Buffett        — avg 5yr pre-tax income x 10  vs  market cap
  2. Brandes        — 4-point value/quality checklist
  3. Pabrai         — ((NI + D&A) - capex) x 10 + cash  vs  market cap
  4. Hartz/Millsap/Hill — 10yr avg ROE / price-to-book
  5. Hempton Nutty  — market cap / revenue (price-to-sales)
"""

import time
from datetime import date
import requests
import yfinance as yf

EDGAR_HEADERS = {"User-Agent": "Bloomberg-Project research@bloomberg-project.com"}

# ── tiny time-based cache ──────────────────────────────────────────────
_cache = {}


def _cache_get(key, ttl):
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < ttl:
            return data
    return None


def _cache_set(key, data):
    _cache[key] = (data, time.time())


# ── SEC EDGAR ──────────────────────────────────────────────────────────
def get_cik(ticker):
    """Return zero-padded 10-digit CIK string for a ticker, or None."""
    cached = _cache_get("cik_map", 86400)
    if cached is None:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=EDGAR_HEADERS, timeout=10,
        )
        r.raise_for_status()
        cached = {e["ticker"].upper(): str(e["cik_str"]).zfill(10)
                  for e in r.json().values()}
        _cache_set("cik_map", cached)
    return cached.get(ticker.upper())


def get_company_facts(cik):
    """Fetch the full XBRL companyfacts blob for a CIK (cached 6h)."""
    key = f"facts_{cik}"
    cached = _cache_get(key, 21600)
    if cached is not None:
        return cached
    r = requests.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
        headers=EDGAR_HEADERS, timeout=20,
    )
    r.raise_for_status()
    facts = r.json()
    _cache_set(key, facts)
    return facts


# GAAP concept aliases — first one that has data wins.
CONCEPTS = {
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
        "IncomeLossBeforeIncomeTaxExpenseBenefit",
    ],
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "depreciation": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebt",
    ],
    "short_term_debt": [
        "DebtCurrent",
        "ShortTermBorrowings",
        "OtherShortTermBorrowings",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "LongTermDebtCurrent",
    ],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "preferred_stock": ["PreferredStockValue", "PreferredStockValueOutstanding"],
    "goodwill": ["Goodwill"],
    "intangibles": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    "shares": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
}


def _year_values(node):
    """
    From one XBRL concept node, return {calendar_year: value} for annual
    (10-K) data points, keyed by the period END date rather than the filer's
    'fy' tag (which mis-attributes prior-year comparatives). Duration facts
    (income / cash-flow) are restricted to ~full-year periods.
    """
    out = {}
    for recs in node.get("units", {}).values():
        for rec in recs:
            if rec.get("form") != "10-K":
                continue
            val, end = rec.get("val"), rec.get("end")
            if val is None or not end:
                continue
            start = rec.get("start")
            if start:  # duration → keep only ~annual spans
                try:
                    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                except ValueError:
                    continue
                if days < 350 or days > 380:
                    continue
            year = int(end[:4])
            # rank: prefer the full-year period, then the most recently filed
            rank = (1 if rec.get("fp") == "FY" else 0, rec.get("filed", ""))
            cur = out.get(year)
            if cur is None or rank > cur[1]:
                out[year] = (val, rank)
    return {y: v[0] for y, v in out.items()}


def annual_series(facts, concept_key):
    """
    Return {calendar_year: value} for a concept. Aliases are tried in priority
    order and *merged*: a higher-priority tag wins for any year it covers, and
    lower-priority tags backfill the remaining years (so a company switching
    GAAP tags over time still yields a continuous series).
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei = facts.get("facts", {}).get("dei", {})
    result = {}
    for gname in CONCEPTS[concept_key]:
        node = us_gaap.get(gname) or dei.get(gname)
        if not node:
            continue
        for year, val in _year_values(node).items():
            result.setdefault(year, val)
    return result


def _latest(series):
    """Most recent (fy, value) from a {fy: val} dict, or (None, None)."""
    if not series:
        return None, None
    fy = max(series)
    return fy, series[fy]


def _at(series, year, default=None):
    """Value for a specific fiscal year, with a fallback to the latest year."""
    if not series:
        return default
    if year in series:
        return series[year]
    return default


# ── helpers for building display rows ──────────────────────────────────
def _num(x):
    return x if isinstance(x, (int, float)) else None


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# ── METHOD 1: BUFFETT ───────────────────────────────────────────────────
def buffett(facts, market_cap):
    series = annual_series(facts, "pretax_income")
    years = sorted(series.keys())[-5:]
    points = [{"year": y, "value": series[y]} for y in years]
    available = len(points) >= 1 and market_cap is not None

    avg = sum(p["value"] for p in points) / len(points) if points else None
    fair_value = avg * 10 if avg is not None else None
    verdict, verdict_class = "—", "neutral"
    if available and fair_value is not None:
        if fair_value >= market_cap:
            verdict, verdict_class = "UNDERVALUED", "good"
        else:
            verdict, verdict_class = "OVERVALUED", "bad"

    return {
        "id": "buffett",
        "name": "Buffett Method",
        "kind": "valuation",
        "formula": "Fair Value = (avg 5yr pre-tax income) × 10   →   compare to market cap",
        "available": available,
        "verdict": verdict,
        "verdict_class": verdict_class,
        "points": points,                 # per-year pre-tax income
        "avg_pretax": avg,
        "fair_value": fair_value,
        "market_cap": market_cap,
        "note": "Undervalued when 10× average pre-tax earnings exceeds the market cap.",
    }


# ── METHOD 2: BRANDES (checklist) ────────────────────────────────────────
def brandes(facts, info, market_cap):
    checks = []

    # Check 1 — no net-income losses in past 5 years
    ni = annual_series(facts, "net_income")
    ni_years = sorted(ni.keys())[-5:]
    ni_points = [{"year": y, "value": ni[y]} for y in ni_years]
    losses = [p for p in ni_points if p["value"] < 0]
    c1_ok = len(ni_points) >= 1 and len(losses) == 0
    checks.append({
        "label": "1. No net-income losses (past 5 yrs)",
        "formula": "every year: Net Income > 0",
        "points": ni_points,
        "detail": (f"{len(losses)} loss year(s) of {len(ni_points)}"
                   if ni_points else "no data"),
        "pass": c1_ok,
        "available": len(ni_points) >= 1,
    })

    # Check 2 — total debt / tangible common equity < 1.0
    # All balance-sheet items are read at the same reference fiscal year (the
    # latest year equity is reported) so the ratio is internally consistent.
    eq_series = annual_series(facts, "total_equity")
    ref_year, eq = _latest(eq_series)
    lt = _at(annual_series(facts, "long_term_debt"), ref_year)
    st = _at(annual_series(facts, "short_term_debt"), ref_year)
    pref = _at(annual_series(facts, "preferred_stock"), ref_year, 0)
    gw = _at(annual_series(facts, "goodwill"), ref_year, 0)
    intan = _at(annual_series(facts, "intangibles"), ref_year, 0)
    # Total debt: prefer yFinance's combined figure (handles companies that
    # split short-term debt across several balance-sheet lines); fall back to
    # the EDGAR LT + ST sum.
    edgar_debt = (lt or 0) + (st or 0) if (lt is not None or st is not None) else None
    yf_debt = _num(info.get("totalDebt"))
    total_debt = yf_debt if yf_debt is not None else edgar_debt
    debt_source = "yFinance" if yf_debt is not None else "SEC EDGAR (LT+ST)"
    tce = (eq - (pref or 0) - (gw or 0) - (intan or 0)) if eq is not None else None
    ratio2 = _div(total_debt, tce)
    c2_ok = ratio2 is not None and tce > 0 and ratio2 < 1.0
    checks.append({
        "label": "2. Total debt / tangible common equity < 1.00",
        "formula": "(LT debt + ST debt) ÷ (equity − preferred − goodwill − intangibles)",
        "year": ref_year,
        "debt_source": debt_source,
        "inputs": {"lt_debt": lt, "st_debt": st, "total_debt": total_debt,
                   "equity": eq, "preferred": pref or 0, "goodwill": gw or 0,
                   "intangibles": intan or 0, "tangible_common_equity": tce},
        "value": ratio2,
        "pass": c2_ok,
        "available": ratio2 is not None,
    })

    # Check 3 — price / book value per share < 1.0
    # Computed as market cap ÷ book equity (identical to price ÷ BVPS, but
    # immune to multi-share-class quirks in yFinance's per-share figures).
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    bvps = _div(eq, shares)
    ratio3 = _div(market_cap, eq)
    if ratio3 is None:
        ratio3 = _div(price, bvps)
    if ratio3 is None:
        ratio3 = _num(info.get("priceToBook"))
    c3_ok = ratio3 is not None and ratio3 > 0 and ratio3 < 1.0
    checks.append({
        "label": "3. Price / book value per share < 1.00",
        "formula": "current price ÷ (total equity ÷ shares outstanding)  =  market cap ÷ total equity",
        "inputs": {"price": price, "equity": eq, "shares": shares, "bvps": bvps,
                   "market_cap": market_cap, "yf_price_to_book": _num(info.get("priceToBook"))},
        "value": ratio3,
        "pass": c3_ok,
        "available": ratio3 is not None,
    })

    # Check 4 — earnings yield (1/PE) > 18%
    pe = _num(info.get("trailingPE"))
    ey = _div(1, pe)
    c4_ok = ey is not None and ey > 0.18
    checks.append({
        "label": "4. Earnings yield (1 / P/E) > 18%",
        "formula": "1 ÷ trailing P/E  >  0.18",
        "inputs": {"pe_ratio": pe, "earnings_yield": ey},
        "value": ey,
        "pass": c4_ok,
        "available": ey is not None,
    })

    passed = sum(1 for c in checks if c.get("available") and c["pass"])
    testable = sum(1 for c in checks if c.get("available"))
    all_pass = testable == 4 and passed == 4
    return {
        "id": "brandes",
        "name": "Brandes Method",
        "kind": "checklist",
        "formula": "4-point value & quality checklist — stock passes when all 4 pass.",
        "available": testable >= 1,
        "verdict": "PASS" if all_pass else ("FAIL" if testable == 4 else f"{passed}/{testable} CHECKS"),
        "verdict_class": "good" if all_pass else ("bad" if testable == 4 else "neutral"),
        "passed": passed,
        "testable": testable,
        "checks": checks,
        "note": "A Graham/Brandes-style screen: consistent profits, low leverage, "
                "trading below book, and a fat earnings yield.",
    }


# ── METHOD 3: PABRAI ──────────────────────────────────────────────────────
def pabrai(facts, info, market_cap):
    # Anchor all three flow items to the same fiscal year (latest net income),
    # falling back to each item's own latest year if it's missing that year.
    ni_series = annual_series(facts, "net_income")
    dep_series = annual_series(facts, "depreciation")
    capex_series = annual_series(facts, "capex")
    fy_ni, ni = _latest(ni_series)
    dep = _at(dep_series, fy_ni)
    fy_dep = fy_ni if dep is not None else None
    if dep is None:
        fy_dep, dep = _latest(dep_series)
    capex = _at(capex_series, fy_ni)
    fy_capex = fy_ni if capex is not None else None
    if capex is None:
        fy_capex, capex = _latest(capex_series)
    cash = _num(info.get("totalCash"))

    owner_earnings = None
    if ni is not None and dep is not None and capex is not None:
        owner_earnings = (ni + dep) - capex
    fair_value = None
    if owner_earnings is not None and cash is not None:
        fair_value = owner_earnings * 10 + cash

    available = fair_value is not None and market_cap is not None
    verdict, verdict_class = "—", "neutral"
    if available:
        if fair_value >= market_cap:
            verdict, verdict_class = "UNDERVALUED", "good"
        else:
            verdict, verdict_class = "OVERVALUED", "bad"

    return {
        "id": "pabrai",
        "name": "Pabrai Method",
        "kind": "valuation",
        "formula": "Fair Value = ((Net Income + D&A) − CapEx) × 10 + cash & securities   →   vs market cap",
        "available": available,
        "verdict": verdict,
        "verdict_class": verdict_class,
        "inputs": {
            "net_income": ni, "net_income_year": fy_ni,
            "depreciation": dep, "depreciation_year": fy_dep,
            "capex": capex, "capex_year": fy_capex,
            "cash": cash,
        },
        "owner_earnings": owner_earnings,
        "fair_value": fair_value,
        "market_cap": market_cap,
        "note": "Pabrai's 'free cash flow x10 plus cash' floor. Undervalued when it exceeds the market cap.",
    }


# ── METHOD 4: HARTZ / MILLSAP / HILL ──────────────────────────────────────
def hartz_millsap_hill(facts, info, market_cap):
    ni = annual_series(facts, "net_income")
    eq = annual_series(facts, "total_equity")
    common_years = sorted(set(ni) & set(eq))[-10:]
    roe_points = []
    for y in common_years:
        r = _div(ni[y], eq[y])
        if r is not None:
            roe_points.append({"year": y, "roe": r,
                               "net_income": ni[y], "equity": eq[y]})
    avg_roe = (sum(p["roe"] for p in roe_points) / len(roe_points)
               if roe_points else None)
    # price-to-book = market cap ÷ latest book equity (robust); fall back to yFinance
    _, eq_latest = _latest(eq)
    pb = _div(market_cap, eq_latest)
    if pb is None:
        pb = _num(info.get("priceToBook"))
    score = _div(avg_roe, pb)

    available = score is not None
    # Higher score = more quality per unit of price paid. Soft guidance only.
    verdict, verdict_class = "—", "neutral"
    if available:
        if score >= 0.15:
            verdict, verdict_class = "ATTRACTIVE", "good"
        elif score < 0.05:
            verdict, verdict_class = "EXPENSIVE", "bad"
        else:
            verdict, verdict_class = "FAIR", "neutral"

    return {
        "id": "hmh",
        "name": "Hartz · Millsap · Hill Method",
        "kind": "score",
        "formula": "Score = (10yr average ROE) ÷ price-to-book ratio",
        "available": available,
        "verdict": verdict,
        "verdict_class": verdict_class,
        "roe_points": roe_points,
        "avg_roe": avg_roe,
        "price_to_book": pb,
        "score": score,
        "note": "Quality-per-price: high long-run ROE relative to the multiple paid on book value.",
    }


# ── METHOD 5: HEMPTON NUTTY ───────────────────────────────────────────────
def hempton_nutty(info, market_cap):
    revenue = _num(info.get("totalRevenue"))
    ps = _div(market_cap, revenue)
    available = ps is not None
    verdict, verdict_class = "—", "neutral"
    if available:
        if ps <= 2:
            verdict, verdict_class = "CHEAP", "good"
        elif ps >= 10:
            verdict, verdict_class = "RICH", "bad"
        else:
            verdict, verdict_class = "MODERATE", "neutral"
    return {
        "id": "hempton",
        "name": "Hempton Nutty Method",
        "kind": "score",
        "formula": "Price-to-Sales = market cap ÷ revenue",
        "available": available,
        "verdict": verdict,
        "verdict_class": verdict_class,
        "market_cap": market_cap,
        "revenue": revenue,
        "price_to_sales": ps,
        "note": "Lower price-to-sales is cheaper. A blunt sanity check on the revenue multiple.",
    }


# ── orchestrator ──────────────────────────────────────────────────────────
def compute_valuation(symbol):
    symbol = symbol.strip().upper()
    cik = get_cik(symbol)
    if not cik:
        return {"error": f"No SEC EDGAR CIK found for '{symbol}'. "
                         "US-listed tickers with 10-K filings only."}
    try:
        facts = get_company_facts(cik)
    except Exception as e:
        return {"error": f"Could not load SEC EDGAR data: {e}"}

    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        info = {}

    market_cap = _num(info.get("marketCap"))
    if market_cap is None:
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        shares = info.get("sharesOutstanding")
        if price and shares:
            market_cap = price * shares

    company = (info.get("longName") or info.get("shortName")
               or facts.get("entityName") or symbol)

    return {
        "symbol": symbol,
        "company": company,
        "cik": cik,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "market_cap": market_cap,
        "currency": info.get("currency", "USD"),
        "methods": [
            buffett(facts, market_cap),
            brandes(facts, info, market_cap),
            pabrai(facts, info, market_cap),
            hartz_millsap_hill(facts, info, market_cap),
            hempton_nutty(info, market_cap),
        ],
    }


if __name__ == "__main__":
    import json
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(compute_valuation(sym), indent=2, default=str))
