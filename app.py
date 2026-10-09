import os
from flask import Flask, jsonify, request, render_template, Response
from service import Parknova
from billing import ParkingError

def create_app(db_path=None):
    app = Flask(__name__); P = Parknova(db_path or os.environ.get("PARKNOVA_DB", "parknova.db"))
    def api(fn):
        def w(*a, **k):
            try: return jsonify(fn(*a, **k))
            except ParkingError as e: return jsonify(error=str(e)), 400
            except Exception as e: return jsonify(error=f"Server error: {e}"), 500
        w.__name__ = f"{fn.__name__}_{id(fn)}"; return w
    j = lambda: request.get_json(silent=True) or {}
    @app.get("/")
    def index(): return render_template("index.html")
    app.get("/api/dashboard")(api(P.dashboard))
    app.get("/api/slots")(api(P.slots))
    app.get("/api/events")(api(P.events))
    app.get("/api/transactions")(api(P.transactions))
    app.get("/api/analytics")(api(P.analytics))
    app.get("/api/search")(api(lambda: P.search(request.args.get("q"))))
    app.get("/api/recommend")(api(lambda: P.recommend(request.args.get("vtype", "2W"))))
    app.get("/api/receipt/<rid>")(api(lambda rid: P.receipt(rid)))
    app.post("/api/checkin")(api(lambda: P.checkin(j().get("reg"), j().get("vtype"), j().get("owner"), j().get("hour"))))
    app.post("/api/checkout")(api(lambda: P.checkout(j().get("query"), j().get("hour"))))
    app.post("/api/demo/load")(api(lambda: (P.load_demo(), {"ok": True})[1]))
    app.post("/api/demo/reset")(api(lambda: (P.reset_demo(), {"ok": True})[1]))
    @app.get("/api/export.csv")
    def export(): return Response(P.export_csv(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=parknova_sessions.csv"})
    return app

if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
