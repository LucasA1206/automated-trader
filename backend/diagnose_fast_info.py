import yfinance as yf

tk = yf.Ticker("AAPL")
fast = tk.fast_info
print("Fast Info keys and values:")
for k in dir(fast):
    if not k.startswith("_"):
        try:
            print(f"  {k}: {getattr(fast, k)}")
        except Exception as e:
            print(f"  {k} failed: {e}")
