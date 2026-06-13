"""Quick test to hit the register endpoint and print the full response."""
import urllib.request
import urllib.error
import json

url = "http://127.0.0.1:8001/api/v1/auth/register"
data = json.dumps({"device_id": "test-device-999", "pin": "1234", "display_name": "Test User"}).encode()

req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req)
    print("SUCCESS:", resp.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}:", e.read().decode())
