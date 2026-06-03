from openbb import obb
import pandas as pd

stocks = ["AAPL", "MSFT", "GOOGL", "JPM", "XOM", "WMT", "KO", "HD"]

rows = []

for stock in stocks:
    try:
        data = obb.equity.fundamental.metrics(symbol=stock)

        r = data.results[0]

        rows.append({
            "Symbol": stock,
            "PE": r.pe_ratio,
            "PB": r.price_to_book,
            "ROE": r.return_on_equity,
            "Debt/Equity": r.debt_to_equity,
            "Current Ratio": r.current_ratio
        })

    except:
        pass

df = pd.DataFrame(rows)

df.to_excel(
    "Value_Screener.xlsx",
    index=False
)

print("Excel file created.")