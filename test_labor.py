"""End-to-end test for the Labor Management sub-ledger."""
import httpx
import json

BASE = "http://127.0.0.1:8001/api/v1"

def test():
    # Use a known farm from the production DB
    # The dev bypass auth returns uid=dev-user-001, but the production
    # farm id=2 belongs to a different user. We'll test with farm_id=6
    # (owned by testuser) and temporarily skip ownership check by
    # directly testing the laborer model layer instead.
    # 
    # Actually — let's test via the API but with a farm that exists.
    # The _verify_farm_ownership will fail for dev-user-001 since no
    # farm is owned by that user. Let's create test data directly.
    
    from app.database import SessionLocal
    from app.models.user import User
    from app.models.farm import Farm
    from app.models.laborer import Laborer
    from app.models.khata import KhataTransaction
    from datetime import date
    
    db = SessionLocal()
    
    # Ensure dev-user-001 exists in users table
    dev_user = db.query(User).filter(User.id == "dev-user-001").first()
    if not dev_user:
        dev_user = User(
            id="dev-user-001",
            display_name="Dev Farmer",
            pin_hash="$2b$12$LJ3m4ys3LzgJqyEyQJGGceDSH7kHmHZwLePGRLv1E23456789abc",  # dummy hash
        )
        db.add(dev_user)
        db.commit()
        print("   Created dev-user-001 in users table")
    
    # Create a dev farm
    dev_farm = db.query(Farm).filter(Farm.user_id == "dev-user-001").first()
    if not dev_farm:
        dev_farm = Farm(
            user_id="dev-user-001",
            name="Dev Test Farm",
            area_acres=5.0,
            soil_type="Black",
            district="Indore",
            state="Madhya Pradesh",
        )
        db.add(dev_farm)
        db.commit()
        db.refresh(dev_farm)
        print(f"   Created dev farm id={dev_farm.id}")
    
    farm_id = dev_farm.id
    db.close()
    
    print(f"   Using farm: id={farm_id}, name=Dev Test Farm")

    # 2. Create a laborer
    print(f"\n2. POST /farms/{farm_id}/laborers")
    r = httpx.post(f"{BASE}/farms/{farm_id}/laborers", json={
        "name": "Ramesh Kumar",
        "phone_number": "9876543210",
    })
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")
    assert r.status_code == 201, f"Expected 201, got {r.status_code}"
    laborer = r.json()
    laborer_id = laborer["id"]
    assert laborer["current_balance"] == 0.0

    # 3. Create a second laborer
    print(f"\n3. POST /farms/{farm_id}/laborers (second)")
    r = httpx.post(f"{BASE}/farms/{farm_id}/laborers", json={
        "name": "Suresh Yadav",
    })
    print(f"   Status: {r.status_code}")
    assert r.status_code == 201

    # 4. Add a labor_wage transaction (Rs 5000 owed to Ramesh)
    print(f"\n4. POST /khata/transactions (labor_wage Rs 5000)")
    r = httpx.post(f"{BASE}/khata/transactions", json={
        "type": "labor_wage",
        "amount": 5000,
        "category": "labor_wage",
        "description": "One week field work",
        "farm_id": farm_id,
        "laborer_id": laborer_id,
    })
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")
    assert r.status_code == 201

    # 5. Add another labor_wage (Rs 3000 more owed)
    print(f"\n5. POST /khata/transactions (labor_wage Rs 3000)")
    r = httpx.post(f"{BASE}/khata/transactions", json={
        "type": "labor_wage",
        "amount": 3000,
        "category": "labor_wage",
        "description": "Weekend harvest help",
        "farm_id": farm_id,
        "laborer_id": laborer_id,
    })
    print(f"   Status: {r.status_code}")
    assert r.status_code == 201

    # 6. Add a labor_payment (Rs 2000 paid to Ramesh)
    print(f"\n6. POST /khata/transactions (labor_payment Rs 2000)")
    r = httpx.post(f"{BASE}/khata/transactions", json={
        "type": "labor_payment",
        "amount": 2000,
        "category": "labor_payment",
        "description": "Partial payment",
        "farm_id": farm_id,
        "laborer_id": laborer_id,
    })
    print(f"   Status: {r.status_code}")
    assert r.status_code == 201

    # 7. List laborers — verify Ramesh's balance = 5000 + 3000 - 2000 = 6000
    print(f"\n7. GET /farms/{farm_id}/laborers (balance check)")
    r = httpx.get(f"{BASE}/farms/{farm_id}/laborers?active_only=false")
    print(f"   Status: {r.status_code}")
    laborers = r.json()
    for l in laborers:
        print(f"   {l['name']:20s} | Balance: Rs {l['current_balance']}")

    ramesh = [l for l in laborers if l["id"] == laborer_id][0]
    assert ramesh["current_balance"] == 6000.0, f"Expected 6000, got {ramesh['current_balance']}"
    print(f"\n   BALANCE CHECK PASSED: Ramesh owes Rs {ramesh['current_balance']}")

    # 8. Get single laborer
    print(f"\n8. GET /farms/{farm_id}/laborers/{laborer_id}")
    r = httpx.get(f"{BASE}/farms/{farm_id}/laborers/{laborer_id}")
    print(f"   Status: {r.status_code}")
    print(f"   Balance: Rs {r.json()['current_balance']}")
    assert r.json()["current_balance"] == 6000.0

    # 9. Test validation: labor_wage without laborer_id should fail
    print(f"\n9. POST /khata/transactions (labor_wage WITHOUT laborer_id — expect 422)")
    r = httpx.post(f"{BASE}/khata/transactions", json={
        "type": "labor_wage",
        "amount": 1000,
        "category": "labor_wage",
        "farm_id": farm_id,
    })
    print(f"   Status: {r.status_code} (expected 422)")
    assert r.status_code == 422

    # 10. Update laborer
    print(f"\n10. PATCH /farms/{farm_id}/laborers/{laborer_id}")
    r = httpx.patch(f"{BASE}/farms/{farm_id}/laborers/{laborer_id}", json={
        "phone_number": "9999999999",
    })
    print(f"   Status: {r.status_code}")
    assert r.status_code == 200
    assert r.json()["phone_number"] == "9999999999"

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)

if __name__ == "__main__":
    test()
