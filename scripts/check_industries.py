import sys, os; sys.path.insert(0, '.'); sys.path.insert(0, 'backend')
from dotenv import load_dotenv; load_dotenv('.env.local')
import finnhub
client = finnhub.Client(api_key=os.getenv('FINNHUB_API'))
tickers = ['FRD','STRZ','SYRE','CLDT','GEO','AMN','NWPX','MOV']
for t in tickers:
    p = client.company_profile2(symbol=t)
    print(t, ':', p.get('finnhubIndustry'), '|', p.get('gsector'))
