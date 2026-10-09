import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from service import Parknova
from billing import calculate_fee, ParkingError
from app import create_app

@pytest.fixture
def P(tmp_path): return Parknova(str(tmp_path / "t.db"))

def fee(o, v, a, b): return calculate_fee(o, v, a, b)["fee"]

def test_slots_init(P):
    s = P.slots(); assert len(s) == 15 and not any(x["occupied"] for x in s)
    assert sum(x["vtype"] == "2W" for x in s) == 10 and s[0]["id"] == "F-01"

def test_allocation_zones(P):
    assert P.checkin("KA01AA0001", "2W", "STUDENT", 9)["slot"] == "T-01"
    assert P.checkin("KA01AA0002", "2W", "STUDENT", 9)["slot"] == "T-02"
    assert P.checkin("KA01BB0001", "4W", "STAFF", 9)["slot"] == "F-01"

def test_full_zone(P):
    for i in range(5): P.checkin(f"KA01FF000{i}", "4W", "VISITOR", 8)
    with pytest.raises(ParkingError, match="full"): P.checkin("KA01FF9999", "4W", "VISITOR", 8)
    assert P.checkin("KA01TT0000", "2W", "VISITOR", 8)["slot"] == "T-01"

def test_duplicate_active(P):
    P.checkin("KA01AA0001", "2W", "STUDENT", 9)
    with pytest.raises(ParkingError, match="already parked"): P.checkin("ka-01 aa 0001", "2W", "STAFF", 9)

def test_fees():
    assert fee("STAFF", "4W", 0, 23) == 0
    assert [fee("STUDENT", "2W", 9, 9 + h) for h in (0, 1, 2, 3, 4)] == [0, 0, 0, 10, 20]
    assert fee("STUDENT", "4W", 9, 13) == 40
    assert fee("VISITOR", "2W", 9, 12) == 60 and fee("VISITOR", "4W", 9, 11) == 80 and fee("VISITOR", "2W", 9, 9) == 0

@pytest.mark.parametrize("a,b", [(-1, 5), (5, 24), ("x", 5), (10, 9), (None, 3)])
def test_invalid_times(a, b):
    with pytest.raises(ParkingError): calculate_fee("STUDENT", "2W", a, b)

def test_invalid_entry_logged(P):
    with pytest.raises(ParkingError): P.checkin("KA01AA0001", "2W", "STUDENT", 30)
    assert P.events()[0]["kind"] == "REJECTED"

def test_search(P):
    P.checkin("KA01AA0001", "2W", "STUDENT", 9)
    assert P.search("ka01aa0001")[0]["slot_id"] == "T-01" and P.search("T-01")[0]["reg"] == "KA01AA0001"
    assert P.search("T-02")[0]["status"] == "AVAILABLE" and P.search("KA09ZZ9999") == []

def test_checkout_release_and_duplicate(P):
    P.checkin("KA01AA0001", "2W", "STUDENT", 9)
    r = P.checkout("KA01AA0001", 13)
    assert r["fee"] == 20 and r["breakdown"]["chargeable_hours"] == 2 and r["receipt_id"].startswith("RCP-")
    assert not [s for s in P.slots() if s["id"] == "T-01"][0]["occupied"]
    with pytest.raises(ParkingError): P.checkout("KA01AA0001", 13)
    assert P.dashboard()["revenue_today"] == 20

def test_bad_checkout_keeps_slot(P):
    P.checkin("KA01AA0001", "2W", "STUDENT", 9)
    with pytest.raises(ParkingError): P.checkout("T-01", 8)
    assert P.dashboard()["occupied"] == 1

def test_persistence(tmp_path):
    p = str(tmp_path / "p.db"); A = Parknova(p); A.checkin("KA01AA0001", "2W", "STAFF", 9)
    B = Parknova(p); assert B.dashboard()["occupied"] == 1 and B.search("T-01")[0]["reg"] == "KA01AA0001"

def test_dashboard_and_alerts(P):
    for i in range(4): P.checkin(f"KA01FF000{i}", "4W", "VISITOR", 8)
    d = P.dashboard(); assert d["occupancy_pct"] == 27 and d["alerts"][0]["level"] == "amber"
    assert d["zones"]["4W"]["available"] == 1

def test_demo_safe(P):
    P.checkin("KA01REAL001", "2W", "STAFF", 9); P.load_demo(); assert P.dashboard()["revenue_today"] == 100
    P.reset_demo(); assert P.dashboard()["occupied"] == 1 and P.transactions() == []

def test_http(tmp_path):
    c = create_app(str(tmp_path / "h.db")).test_client()
    assert c.post("/api/checkin", json={"reg": "KA01AA0001", "vtype": "2W", "owner": "Student", "hour": 9}).status_code == 200
    assert c.post("/api/checkin", json={"reg": "KA01AA0001", "vtype": "2W", "owner": "Student", "hour": 9}).status_code == 400
    assert c.post("/api/checkout", json={"query": "KA01AA0001", "hour": 13}).get_json()["fee"] == 20
    assert b"receipt_id" in c.get("/api/export.csv").data
