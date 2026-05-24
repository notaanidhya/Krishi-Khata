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

try:
    print("Sending request to data.gov.in with a 90-second timeout...")
    resp = httpx.get(URL, params=PARAMS, timeout=90.0)
    print(f"HTTP {resp.status_code}")
    data = resp.json()
    records = data.get("records", [])
    print(f"Total records returned: {data.get('total', '?')}")
    print(f"Records in this page: {len(records)}")
    for r in records[:3]:
        print(f"  {r.get('commodity', '?'):20s} | {r.get('market', '?'):15s} | ₹{r.get('modal_price', '?')}")
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
