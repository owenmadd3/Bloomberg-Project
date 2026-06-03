from openbb import obb

stocks = ["AAPL", "MSFT", "GOOGL", "JPM", "XOM", "WMT", "KO", "HD"]

def safe_num(value):
    if value is None:
        return "N/A"
    return f"{value:.2f}"

def value_score(pe, pb, roe, debt, current):
    score = 0
    checks = []

    if pe is not None and pe < 25:
        score += 1
        checks.append("P/E")
    if pb is not None and pb < 5:
        score += 1
        checks.append("P/B")
    if roe is not None and roe > 0.15:
        score += 1
        checks.append("ROE")
    if debt is not None and debt < 50:
        score += 1
        checks.append("Debt")
    if current is not None and current > 1:
        score += 1
        checks.append("Current")

    return score, ", ".join(checks)

results = []

for stock in stocks:
    try:
        data = obb.equity.fundamental.metrics(symbol=stock)
        r = data.results[0]

        pe = r.pe_ratio
        pb = r.price_to_book
        roe = r.return_on_equity
        debt = r.debt_to_equity
        current = r.current_ratio

        score, passed_checks = value_score(pe, pb, roe, debt, current)

        results.append({
            "symbol": stock,
            "pe": pe,
            "pb": pb,
            "roe": roe,
            "debt": debt,
            "current": current,
            "score": score,
            "passed_checks": passed_checks
        })

    except Exception as e:
        print(f"{stock}: Error {e}")

results = sorted(results, key=lambda x: x["score"], reverse=True)

print("\nTOP VALUE CANDIDATES")
print("=" * 115)
print(
    f"{'Rank':<6}"
    f"{'Symbol':<8}"
    f"{'P/E':>10}"
    f"{'P/B':>10}"
    f"{'ROE':>12}"
    f"{'Debt/Eq':>12}"
    f"{'Current':>12}"
    f"{'Score':>10}"
    f"{'Passed Checks':>25}"
)
print("-" * 115)

for i, item in enumerate(results, start=1):
    print(
        f"{i:<6}"
        f"{item['symbol']:<8}"
        f"{safe_num(item['pe']):>10}"
        f"{safe_num(item['pb']):>10}"
        f"{safe_num(item['roe']):>12}"
        f"{safe_num(item['debt']):>12}"
        f"{safe_num(item['current']):>12}"
        f"{str(item['score']) + '/5':>10}"
        f"{item['passed_checks']:>25}"
    )