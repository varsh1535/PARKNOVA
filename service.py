"""Business logic + SQLite data access."""
import sqlite3, re, csv, io, json, uuid
from contextlib import closing
from datetime import datetime
from billing import calculate_fee, check_hour, ParkingError, OWNERS, VTYPES

SCHEMA = """
CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY, vtype TEXT NOT NULL CHECK(vtype IN('2W','4W')));
CREATE TABLE IF NOT EXISTS sessions(
 id INTEGER PRIMARY KEY AUTOINCREMENT, reg TEXT NOT NULL, vtype TEXT NOT NULL,
 owner TEXT NOT NULL CHECK(owner IN('STAFF','STUDENT','VISITOR')),
 slot_id TEXT NOT NULL REFERENCES slots(id), entry_hour INTEGER NOT NULL CHECK(entry_hour BETWEEN 0 AND 23),
 exit_hour INTEGER CHECK(exit_hour BETWEEN 0 AND 23), status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN('ACTIVE','DONE')),
 fee INTEGER CHECK(fee>=0), receipt_id TEXT UNIQUE, breakdown TEXT, checkin_ts TEXT, checkout_ts TEXT, demo INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_reg ON sessions(reg) WHERE status='ACTIVE';
CREATE UNIQUE INDEX IF NOT EXISTS one_active_slot ON sessions(slot_id) WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, msg TEXT, demo INTEGER DEFAULT 0);
"""
SLOT_RE = re.compile(r"^[TF]-\d{2}$")
now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalize_reg(r):
    r = re.sub(r"[\s\-]", "", str(r or "").upper())
    if not re.fullmatch(r"[A-Z0-9]{4,12}", r):
        raise ParkingError("Registration must be 4-12 letters/digits (e.g. KA01AB1234).")
    return r

def logged(fn):
    """Persist rejected attempts to the activity log."""
    def w(self, *a, **k):
        try: return fn(self, *a, **k)
        except ParkingError as e:
            self.log("REJECTED", str(e)); raise
    return w

class Parknova:
    def __init__(self, path="parknova.db"):
        self.path = path
        with closing(self._c()) as c, c:
            c.executescript(SCHEMA)
            if not c.execute("SELECT 1 FROM slots").fetchone():
                c.executemany("INSERT INTO slots VALUES(?,?)",
                    [(f"T-{i:02d}", "2W") for i in range(1, 11)] + [(f"F-{i:02d}", "4W") for i in range(1, 6)])

    def _c(self):
        c = sqlite3.connect(self.path); c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON"); return c

    def _q(self, sql, args=()):
        with closing(self._c()) as c: return [dict(r) for r in c.execute(sql, args).fetchall()]

    def log(self, kind, msg, demo=0):
        with closing(self._c()) as c, c:
            c.execute("INSERT INTO events(ts,kind,msg,demo) VALUES(?,?,?,?)", (now(), kind, msg, demo))

    # ---- allocation (modular policy: lowest-numbered free slot in the matching zone)
    @staticmethod
    def allocate(c, vtype):
        r = c.execute("SELECT id FROM slots WHERE vtype=? AND id NOT IN "
                      "(SELECT slot_id FROM sessions WHERE status='ACTIVE') ORDER BY id LIMIT 1", (vtype,)).fetchone()
        return r["id"] if r else None

    @logged
    def checkin(self, reg, vtype, owner, hour, demo=0):
        reg = normalize_reg(reg); owner = str(owner).upper(); hour = check_hour(hour, "Entry hour")
        if vtype not in VTYPES: raise ParkingError("Vehicle type must be two-wheeler or four-wheeler.")
        if owner not in OWNERS: raise ParkingError("Owner must be Staff, Student or Visitor.")
        with closing(self._c()) as c, c:
            if c.execute("SELECT 1 FROM sessions WHERE reg=? AND status='ACTIVE'", (reg,)).fetchone():
                raise ParkingError(f"{reg} is already parked. Duplicate active entries are not allowed.")
            slot = self.allocate(c, vtype)
            if not slot:
                other = "four-wheeler" if vtype == "2W" else "two-wheeler"
                raise ParkingError(f"{VTYPES[vtype]} zone is full. Wait for a checkout; {other} slots cannot be used.")
            c.execute("INSERT INTO sessions(reg,vtype,owner,slot_id,entry_hour,checkin_ts,demo) VALUES(?,?,?,?,?,?,?)",
                      (reg, vtype, owner, slot, hour, now(), demo))
            left = c.execute("SELECT COUNT(*) n FROM slots WHERE vtype=? AND id NOT IN (SELECT slot_id FROM sessions WHERE status='ACTIVE')", (vtype,)).fetchone()["n"]
            c.execute("INSERT INTO events(ts,kind,msg,demo) VALUES(?,?,?,?)",
                      (now(), "ENTRY", f"{reg} ({owner.title()}, {VTYPES[vtype]}) parked in {slot} at {hour:02d}:00", demo))
        return {"reg": reg, "slot": slot, "entry_hour": hour, "zone_remaining": left}

    @logged
    def checkout(self, query, exit_hour):
        q = str(query or "").strip().upper()
        if not q: raise ParkingError("Enter a registration number or slot ID.")
        by_slot = bool(SLOT_RE.match(q))
        key = q if by_slot else normalize_reg(q)
        with closing(self._c()) as c, c:
            s = c.execute(f"SELECT * FROM sessions WHERE status='ACTIVE' AND {'slot_id' if by_slot else 'reg'}=?", (key,)).fetchone()
            if not s: raise ParkingError(f"No parked vehicle found for {key}. It may already be checked out.")
            b = calculate_fee(s["owner"], s["vtype"], s["entry_hour"], exit_hour)
            rid = f"RCP-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            cur = c.execute("UPDATE sessions SET status='DONE',exit_hour=?,fee=?,receipt_id=?,breakdown=?,checkout_ts=? "
                            "WHERE id=? AND status='ACTIVE'", (int(exit_hour), b["fee"], rid, json.dumps(b), now(), s["id"]))
            if cur.rowcount != 1: raise ParkingError("Checkout failed: session already closed.")
            c.execute("INSERT INTO events(ts,kind,msg,demo) VALUES(?,?,?,?)",
                      (now(), "EXIT", f"{s['reg']} left {s['slot_id']} at {int(exit_hour):02d}:00, paid Rs {b['fee']} ({rid})", s["demo"]))
        return self.receipt(rid)

    def receipt(self, rid):
        r = self._q("SELECT * FROM sessions WHERE receipt_id=?", (rid,))
        if not r: raise ParkingError("Receipt not found.")
        r = r[0]; r["breakdown"] = json.loads(r["breakdown"]); return r

    def slots(self):
        return self._q("SELECT s.id,s.vtype,x.reg,x.owner,x.entry_hour,x.checkin_ts, x.id IS NOT NULL AS occupied "
                       "FROM slots s LEFT JOIN sessions x ON x.slot_id=s.id AND x.status='ACTIVE' ORDER BY s.id")

    def search(self, q):
        q = str(q or "").strip().upper()
        if not q: raise ParkingError("Enter a registration number or slot ID.")
        by_slot = bool(SLOT_RE.match(q)); key = q if by_slot else normalize_reg(q)
        col = "slot_id" if by_slot else "reg"
        rows = self._q(f"SELECT reg,vtype,owner,slot_id,entry_hour,exit_hour,status FROM sessions WHERE {col}=? ORDER BY id DESC LIMIT 5", (key,))
        hr = datetime.now().hour
        for r in rows:
            if r["status"] == "ACTIVE":
                r["duration_now"] = (f"{hr - r['entry_hour']} h (clock hour {hr:02d})" if hr >= r["entry_hour"]
                                     else "n/a (entry hour is later than current clock hour)")
        if by_slot and not any(r["status"] == "ACTIVE" for r in rows):
            if self._q("SELECT 1 FROM slots WHERE id=?", (key,)):
                return [{"slot_id": key, "status": "AVAILABLE"}] 
        return rows

    def dashboard(self):
        sl = self.slots(); out = {"zones": {}}
        for t in VTYPES:
            z = [s for s in sl if s["vtype"] == t]; o = sum(s["occupied"] for s in z)
            out["zones"][t] = {"capacity": len(z), "occupied": o, "available": len(z) - o}
        cap, occ = len(sl), sum(s["occupied"] for s in sl)
        today = datetime.now().strftime("%Y-%m-%d")
        d = self._q("SELECT COUNT(*) n, COALESCE(SUM(fee),0) rev FROM sessions WHERE status='DONE' AND substr(checkout_ts,1,10)=?", (today,))[0]
        out.update(capacity=cap, occupied=occ, available=cap - occ, occupancy_pct=round(100 * occ / cap),
                   parked=occ, completed_today=d["n"], revenue_today=d["rev"], alerts=[])
        for t, z in out["zones"].items():
            pct = 100 * z["occupied"] / z["capacity"]
            if pct == 100: out["alerts"].append({"level": "red", "msg": f"{VTYPES[t]} zone is FULL"})
            elif pct >= 80: out["alerts"].append({"level": "amber", "msg": f"{VTYPES[t]} zone at {round(pct)}% - {z['available']} slot(s) left"})
        return out

    def recommend(self, vtype):
        with closing(self._c()) as c:
            s = self.allocate(c, vtype)
        return {"slot": s, "policy": "Lowest-numbered free slot in the matching zone (no physical distance data)."}

    def events(self, n=30): return self._q("SELECT ts,kind,msg FROM events ORDER BY id DESC LIMIT ?", (n,))

    def transactions(self):
        return self._q("SELECT receipt_id,reg,vtype,owner,slot_id,entry_hour,exit_hour,fee,checkout_ts,demo FROM sessions WHERE status='DONE' ORDER BY id DESC")

    def analytics(self):
        return {"zones": self.dashboard()["zones"],
                "owners": self._q("SELECT owner, COUNT(*) n FROM sessions GROUP BY owner"),
                "revenue": self._q("SELECT owner, COALESCE(SUM(fee),0) rev FROM sessions WHERE status='DONE' GROUP BY owner")}

    def export_csv(self):
        rows = self.transactions(); buf = io.StringIO()
        w = csv.writer(buf); w.writerow(["receipt_id","reg","vtype","owner","slot","entry_hour","exit_hour","fee_inr","checkout_ts"])
        for r in rows: w.writerow([r["receipt_id"],r["reg"],r["vtype"],r["owner"],r["slot_id"],r["entry_hour"],r["exit_hour"],r["fee"],r["checkout_ts"]])
        return buf.getvalue()

    # ---- demo mode (explicit, flagged, safely removable)
    def load_demo(self):
        if self._q("SELECT 1 FROM sessions WHERE demo=1 LIMIT 1"): raise ParkingError("Demo data already loaded.")
        for reg, vt, ow, h, x in [("KA01DM1001","2W","STUDENT",9,13),("KA01DM2002","4W","VISITOR",10,12),
                                  ("KA01DM3003","4W","STAFF",8,None),("KA01DM4004","2W","STUDENT",11,None)]:
            self.checkin(reg, vt, ow, h, demo=1)
            if x is not None: self.checkout(reg, x)

    def reset_demo(self):
        with closing(self._c()) as c, c:
            c.execute("DELETE FROM sessions WHERE demo=1"); c.execute("DELETE FROM events WHERE demo=1")
