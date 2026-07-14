import requests
headers = {'User-Agent': 'Mozilla/5.0'}
url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000"
print('Fetching nasdaq screener...')
try:
    r = requests.get(url, headers=headers)
    rows = r.json()['data']['table']['rows']
    valid = []
    for row in rows:
        try:
            price = float(row['lastsale'].replace('$', '').replace(',', ''))
            if price >= 5:
                valid.append(row['symbol'])
        except Exception:
            pass
    print(f"Total: {len(rows)}, >$5: {len(valid)}")
except Exception as e:
    print('Error:', e)
