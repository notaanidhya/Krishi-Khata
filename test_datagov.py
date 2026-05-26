"""Quick test: hit data.gov.in directly and print result."""
import httpx
import json
import sys

URL = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"
PARAMS = {
    "api-key": "579b464db66ec23bdd000001d2b8a19146b244e15f4d41f2a092aa70",
    "format": "json",
    "limit": "5",
    "filters[State]": "Madhya Pradesh",
    "filters[District]": "Indore",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

try:
    print("Sending request to data.gov.in with a 90-second timeout and custom headers...")
    resp = httpx.get(URL, params=PARAMS, headers=HEADERS, timeout=90.0)
    print(f"HTTP {resp.status_code}")
    data = resp.json()
    records = data.get("records", [])
    print(f"Total records returned: {data.get('total', '?')}")
    for r in records[:3]:
        price = r.get('Modal_Price') or r.get('modal_price', '?')
        commodity = r.get('Commodity') or r.get('commodity', '?')
        market = r.get('Market') or r.get('market', '?')
        print(f"  {commodity:20s} | {market:15s} | Rs. {price}")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
