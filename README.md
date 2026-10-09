# PARKNOVA — Smart Campus Parking & Vehicle Intelligence System
*Every Slot. Every Vehicle. Under Control.*

## Run
    pip install -r requirements.txt
    python app.py            # open http://127.0.0.1:5000
    python -m pytest -q      # 18 automated tests
Data lives in `parknova.db` (SQLite, created on first run; survives restarts). Set `PARKNOVA_DB` to change the path.

## Architecture
- `billing.py` – the single authoritative fee function + hour validation (exit − entry, same day, no rounding).
- `service.py` – `Parknova` class: SQLite schema, allocator, check-in/out (atomic transactions), search, dashboard, analytics, CSV, demo mode.
- `app.py` – thin Flask JSON API; `templates/index.html` – single-page UI (fetches real data only).
- Integrity is enforced in the DB: partial unique indexes allow only ONE active session per registration and per slot; occupancy is derived from active sessions, so a slot is released only when checkout commits.
- Slots: T-01..T-10 (two-wheeler), F-01..F-05 (four-wheeler). Allocation: lowest-numbered free slot in the right zone.

## Rates (per problem statement)
Staff free · Student first 2 h free then ₹10/h (2W) or ₹20/h (4W) · Visitor ₹20/h (2W) or ₹40/h (4W).
Limitation: hour-only input, same day; exit earlier than entry is rejected; no overnight billing.

## Demo script
1. Overview: 15 slots free. 2. Check-in student 2W `KA01AB1234`, hour 9 → T-01. 3. Check-in staff 4W, hour 9 → F-01 (free).
4. Search `KA01AB1234` / `T-01`. 5. Re-check-in same reg → rejected. 6. Check-out `KA01AB1234` at 13 → receipt: 4 h, 2 free, 2×₹10 = ₹20.
7. T-01 is free; metrics/feed/revenue updated. 8. Stop and restart `python app.py` → F-01 still occupied.
(Settings → Load demo data adds flagged sample sessions; Reset removes only those.)

## Checklist
Slots ✔ · Check-in/allocation/validation ✔ · Billing ✔ · Dashboard & grid ✔ · Vehicle finder ✔ · Checkout/receipt/print ✔ · CSV export ✔ · Persistence ✔ · Activity log ✔ · Capacity alerts (≥80%/full) ✔ · Analytics ✔ · Demo mode ✔ · Tests ✔
Not included: backup/import, column sorting, camera/IoT/online payment.

## Pitch
Campus parking is managed on paper, causing wrong fees and double allocation. PARKNOVA enforces correctness at the database level (unique active session per vehicle and slot), bills through one tested function with an itemised explanation, and persists everything in SQLite — a guard can check in a vehicle in three fields.
