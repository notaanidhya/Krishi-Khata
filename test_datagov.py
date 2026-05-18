"""Quick test: hit data.gov.in directly and print result."""
import httpx
import json
import sys

URL = "https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24"
PARAMS = {
    "api-key": "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b",
    "format": "json",
    "limit": "5",
    "filters[State]": "Madhya Pradesh",
    "filters[District]": "Indore",
}

try:
    resp = httpx.get(URL, params=PARAMS, timeout=30.0)
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
