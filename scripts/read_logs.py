import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('backend/blitz_trader.db')
cursor = conn.cursor()
cursor.execute("SELECT timestamp, category, level, message FROM system_logs WHERE category = 'scan' ORDER BY timestamp DESC LIMIT 100")
for row in cursor.fetchall():
    print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]}")
