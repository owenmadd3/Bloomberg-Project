import subprocess

while True:

    print("\nOPENBB BLOOMBERG PROJECT")
    print("=" * 35)
    print("1. Market Dashboard")
    print("2. Commodity Dashboard")
    print("3. Value Screener")
    print("4. Exit")

    choice = input("\nChoose an option: ")

    if choice == "1":
        subprocess.run(["python3", "data/market_dashboard.py"])

    elif choice == "2":
        subprocess.run(["python3", "data/commodity_dashboard.py"])

    elif choice == "3":
        subprocess.run(["python3", "data/value_screener.py"])

    elif choice == "4":
        print("Exiting terminal.")
        break

    else:
        print("Invalid choice.")