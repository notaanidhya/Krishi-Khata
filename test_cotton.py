import httpx, json
resp = httpx.get('https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24', params={'api-key':'579b464db66ec23bdd000001d2b8a19146b244e15f4d41f2a092aa70','format':'json','limit':'10','filters[Commodity]':'Cotton', 'sort[Arrival_Date]':'desc'}, headers={'User-Agent': 'Mozilla/5.0'})
print([f"{r.get('State')} - {r.get('District')} - {r.get('Market')}" for r in resp.json().get('records', [])])
