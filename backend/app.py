"""
app.py
-------
RCAi Flask backend. Run this file to start the local server:

    python app.py

Then open http://127.0.0.1:5000 in your browser.

Routes overview
----------------
POST /api/incidents                          create a new incident
GET  /api/incidents/<id>                      get incident state
POST /api/incidents/<id>/fetch/cloudwatch     pull CloudWatch events
POST /api/incidents/<id>/fetch/site24x7       pull Site24x7 events
POST /api/incidents/<id>/upload               upload a log/CSV/JSON file
POST /api/incidents/<id>/manual-event         add a manually typed event
POST /api/incidents/<id>/generate-rca         run correlation + AI RCA
PUT  /api/incidents/<id>/rca                  save user's edits to the RCA
GET  /api/incidents/<id>/export/<fmt>         download pdf / docx / json
"""

import os
import sys
import json
import uuid
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, send_file, render_template
from dotenv import load_dotenv

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

load_dotenv()

from models.incident import Incident, Event
from connectors.cloudwatch_connector import CloudWatchConnector
from connectors.site24x7_connector import Site24x7Connector
from connectors.log_parser import parse_uploaded_file
from engine.report_generator import build_rca_report
from exporters.pdf_exporter import export_rca_pdf
from exporters.docx_exporter import export_rca_docx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")

os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, "templates"),
    static_folder=os.path.join(FRONTEND_DIR, "static"),
)
if CORS:
    CORS(app)

# In-memory incident store, persisted to disk as JSON so it survives restarts.
INCIDENTS = {}


def _incident_path(incident_id):
    return os.path.join(REPORTS_DIR, f"{incident_id}.json")


def _save_incident(incident_id):
    with open(_incident_path(incident_id), "w") as f:
        json.dump(INCIDENTS[incident_id], f, indent=2, default=str)


def _load_incident(incident_id):
    path = _incident_path(incident_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _get_incident_or_404(incident_id):
    if incident_id in INCIDENTS:
        return INCIDENTS[incident_id]
    loaded = _load_incident(incident_id)
    if loaded:
        INCIDENTS[incident_id] = loaded
        return loaded
    return None


# ------------------------------------------------------------------
# Frontend
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------
# Incident lifecycle
# ------------------------------------------------------------------
@app.route("/api/incidents", methods=["POST"])
def create_incident():
    data = request.get_json(force=True)
    incident_id = "INC-" + datetime.utcnow().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

    incident = Incident(
        incident_id=incident_id,
        title=data.get("title", "Untitled Incident"),
        description=data.get("description", ""),
        reported_by=data.get("reported_by", ""),
        start_time=data.get("start_time") or datetime.utcnow().isoformat(),
        end_time=data.get("end_time") or datetime.utcnow().isoformat(),
    )
    INCIDENTS[incident_id] = incident.to_dict()
    _save_incident(incident_id)
    return jsonify(INCIDENTS[incident_id]), 201


@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    files = [f[:-5] for f in os.listdir(REPORTS_DIR) if f.endswith(".json")]
    summaries = []
    for fid in files:
        inc = _get_incident_or_404(fid)
        if inc:
            summaries.append({
                "incident_id": inc["incident_id"],
                "title": inc["title"],
                "created_at": inc.get("created_at"),
                "has_rca": bool(inc.get("rca_report")),
            })
    summaries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(summaries)


@app.route("/api/incidents/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404
    return jsonify(inc)


# ------------------------------------------------------------------
# Data ingestion
# ------------------------------------------------------------------
@app.route("/api/incidents/<incident_id>/fetch/cloudwatch", methods=["POST"])
def fetch_cloudwatch(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    connector = CloudWatchConnector()
    events = connector.fetch_events(inc["start_time"], inc["end_time"],
                                      resource=request.get_json(silent=True, force=True).get("resource", "prod-app-server")
                                      if request.get_json(silent=True) else "prod-app-server")
    inc["events"].extend([e.to_dict() for e in events])
    _save_incident(incident_id)
    return jsonify({"added": len(events), "is_demo_mode": not connector.is_configured(), "events": [e.to_dict() for e in events]})


@app.route("/api/incidents/<incident_id>/fetch/site24x7", methods=["POST"])
def fetch_site24x7(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    body = request.get_json(silent=True) or {}
    connector = Site24x7Connector()
    events = connector.fetch_events(inc["start_time"], inc["end_time"],
                                      monitor_name=body.get("monitor_name", "prod-web-app"))
    inc["events"].extend([e.to_dict() for e in events])
    _save_incident(incident_id)
    return jsonify({"added": len(events), "is_demo_mode": not connector.is_configured(), "events": [e.to_dict() for e in events]})


@app.route("/api/incidents/<incident_id>/upload", methods=["POST"])
def upload_file(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    content = f.read().decode("utf-8", errors="ignore")
    events = parse_uploaded_file(f.filename, content)

    save_path = os.path.join(UPLOADS_DIR, f"{incident_id}_{f.filename}")
    with open(save_path, "w") as out:
        out.write(content)

    inc["events"].extend([e.to_dict() for e in events])
    _save_incident(incident_id)
    return jsonify({"added": len(events), "filename": f.filename, "events": [e.to_dict() for e in events]})


@app.route("/api/incidents/<incident_id>/manual-event", methods=["POST"])
def add_manual_event(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    body = request.get_json(force=True)
    event = Event(
        timestamp=body.get("timestamp") or datetime.utcnow().isoformat(),
        source=body.get("source", "Manual"),
        severity=body.get("severity", "info"),
        message=body.get("message", ""),
        resource=body.get("resource"),
    )
    inc["events"].append(event.to_dict())
    _save_incident(incident_id)
    return jsonify(event.to_dict())


# ------------------------------------------------------------------
# RCA generation
# ------------------------------------------------------------------
@app.route("/api/incidents/<incident_id>/generate-rca", methods=["POST"])
def generate_rca_route(incident_id):
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    if not inc["events"]:
        return jsonify({"error": "No events to analyze yet. Fetch or upload data first."}), 400

    events = [Event(**{k: v for k, v in e.items() if k in Event.__dataclass_fields__}) for e in inc["events"]]
    # Pass a lightweight, non-circular snapshot of incident metadata (not the
    # whole incident object, which would otherwise end up embedding itself
    # inside inc["rca_report"] once we save it below).
    incident_meta = {
        "incident_id": inc["incident_id"],
        "title": inc["title"],
        "description": inc["description"],
        "reported_by": inc.get("reported_by", ""),
        "start_time": inc["start_time"],
        "end_time": inc["end_time"],
    }
    report = build_rca_report(incident_meta, events)

    inc["rca_report"] = report
    inc["anomalies"] = report["anomalies"]
    inc["correlation_clusters"] = report["clusters"]
    _save_incident(incident_id)
    return jsonify(report)


@app.route("/api/incidents/<incident_id>/rca", methods=["PUT"])
def update_rca(incident_id):
    """Allows the user to edit the AI-generated RCA content in the UI before export."""
    inc = _get_incident_or_404(incident_id)
    if not inc:
        return jsonify({"error": "Incident not found"}), 404

    body = request.get_json(force=True)
    if not inc.get("rca_report"):
        inc["rca_report"] = {"incident": inc, "clusters": [], "anomalies": [], "rca": {}}
    inc["rca_report"]["rca"] = body.get("rca", inc["rca_report"].get("rca", {}))
    _save_incident(incident_id)
    return jsonify(inc["rca_report"])


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------
@app.route("/api/incidents/<incident_id>/export/<fmt>", methods=["GET"])
def export_report(incident_id, fmt):
    inc = _get_incident_or_404(incident_id)
    if not inc or not inc.get("rca_report"):
        return jsonify({"error": "No RCA report generated yet"}), 400

    report = inc["rca_report"]
    safe_title = "".join(c if c.isalnum() else "_" for c in inc["title"])[:40]

    if fmt == "pdf":
        out_path = os.path.join(REPORTS_DIR, f"{incident_id}_{safe_title}.pdf")
        export_rca_pdf(report, out_path)
        return send_file(out_path, as_attachment=True, download_name=f"RCA_{safe_title}.pdf")

    elif fmt == "docx":
        out_path = os.path.join(REPORTS_DIR, f"{incident_id}_{safe_title}.docx")
        export_rca_docx(report, out_path)
        return send_file(out_path, as_attachment=True, download_name=f"RCA_{safe_title}.docx")

    elif fmt == "json":
        out_path = os.path.join(REPORTS_DIR, f"{incident_id}_{safe_title}.json")
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        return send_file(out_path, as_attachment=True, download_name=f"RCA_{safe_title}.json")

    return jsonify({"error": f"Unsupported format: {fmt}"}), 400


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "ai_configured": bool(os.getenv("ANTHROPIC_API_KEY")),
        "cloudwatch_configured": bool(os.getenv("AWS_ACCESS_KEY_ID")),
        "site24x7_configured": bool(os.getenv("SITE24X7_API_KEY")),
    })


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    print(f"\n RCAi is running -> http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=debug)
