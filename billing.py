"""Single authoritative billing + validation rules (hour-only, same-day)."""
class ParkingError(ValueError):
    """User-facing validation/business-rule error."""

RATES = {"STUDENT": {"2W": 10, "4W": 20}, "VISITOR": {"2W": 20, "4W": 40}}
OWNERS = ("STAFF", "STUDENT", "VISITOR")
VTYPES = {"2W": "Two-wheeler", "4W": "Four-wheeler"}

def check_hour(v, label="Hour"):
    if isinstance(v, bool) or not str(v).strip().lstrip("-").isdigit():
        raise ParkingError(f"{label} must be a whole number from 0 to 23.")
    v = int(v)
    if not 0 <= v <= 23:
        raise ParkingError(f"{label} must be between 0 and 23.")
    return v

def calculate_fee(owner, vtype, entry, exit_):
    """exit - entry hours. Staff free; student first 2h free; visitor flat/hour."""
    owner = str(owner).upper()
    if owner not in OWNERS: raise ParkingError("Owner must be Staff, Student or Visitor.")
    if vtype not in VTYPES: raise ParkingError("Vehicle type must be 2W or 4W.")
    entry, exit_ = check_hour(entry, "Entry hour"), check_hour(exit_, "Exit hour")
    if exit_ < entry:
        raise ParkingError("Exit hour cannot be earlier than entry hour (same-day, hour-only billing).")
    total = exit_ - entry
    rate = 0 if owner == "STAFF" else RATES[owner][vtype]
    free = total if owner == "STAFF" else (min(total, 2) if owner == "STUDENT" else 0)
    chargeable = total - free
    fee = chargeable * rate
    note = ("Staff parking is free." if owner == "STAFF" else
            f"{total} h total, {free} h free, {chargeable} h chargeable x Rs {rate}/h = Rs {fee}")
    return {"total_hours": total, "free_hours": free, "chargeable_hours": chargeable,
            "rate": rate, "fee": fee, "explanation": note}
