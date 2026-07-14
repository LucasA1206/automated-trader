import requests
import yfinance as yf

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

tickers = ["AAPL", "AMAT", "AAON"]
for ticker in tickers:
    try:
        tk = yf.Ticker(ticker, session=session)
        info = tk.info
        print(f"SUCCESS {ticker}: marketCap={info.get('marketCap')}")
    except Exception as e:
        print(f"FAIL {ticker}: {e}")
