from openbb import obb

commodities = {
    "Gold": "GLD",
    "Silver": "SLV",
    "Crude Oil": "USO",
    "Natural Gas": "UNG",
    "Corn": "CORN",
    "Wheat": "WEAT",
    "Soybeans": "SOYB",
}

def safe_num(value):
    if value is None:
        return "N/A"
    return f"{value:.2f}"

print("\nCOMMODITY DASHBOARD")
print("=" * 70)
print(f"{'Commodity':<15}{'Symbol':<8}{'Price':>10}{'Change':>12}{'% Change':>12}")
print("-" * 70)

for name, symbol in commodities.items():
    try:
        data = obb.equity.price.quote(symbol=symbol)

        if data.results:
            r = data.results[0]

            price = r.last_price or r.bid or r.ask or r.prev_close
            change = r.change
            pct = r.change_percent

            print(
                f"{name:<15}"
                f"{symbol:<8}"
                f"{safe_num(price):>10}"
                f"{safe_num(change):>12}"
                f"{safe_num(pct):>12}"
            )
        else:
            print(f"{name:<15}{symbol:<8} No data")

    except Exception as e:
        print(f"{name:<15}{symbol:<8} Error: {e}")