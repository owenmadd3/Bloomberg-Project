from openbb import obb

assets = {
    "S&P 500 ETF": "SPY",
    "Nasdaq ETF": "QQQ",
    "Dow ETF": "DIA",
    "Gold ETF": "GLD",
    "Oil ETF": "USO",
    "Natural Gas ETF": "UNG",
    "Volatility ETF": "VIXY",
}

print("\nMORNING MARKET DASHBOARD")
print("=" * 75)
print(f"{'Asset':<25} {'Symbol':<8} {'Price':>10} {'Prev Close':>12} {'Change':>10} {'% Change':>10}")
print("-" * 75)

for name, symbol in assets.items():
    try:
        data = obb.equity.price.quote(symbol=symbol)

        if data.results:
            r = data.results[0]

            price = r.last_price or r.bid or r.ask or r.prev_close
            prev_close = r.prev_close

            if price is not None and prev_close is not None:
                change = price - prev_close
                percent_change = (change / prev_close) * 100

                print(f"{name:<25} {symbol:<8} ${price:>9.2f} ${prev_close:>11.2f} {change:>10.2f} {percent_change:>9.2f}%")
            else:
                print(f"{name:<25} {symbol:<8} Missing data")

        else:
            print(f"{name:<25} {symbol:<8} No data returned")

    except Exception as e:
        print(f"{name:<25} {symbol:<8} Error: {e}")