"""
engine/report_generator.py
-----------------------------
Orchestrates the full pipeline: correlate -> detect anomalies -> AI RCA.
This is the single function the Flask routes call.
"""

from engine.correlator import correlate
from engine.anomaly_detector import detect_anomalies
from engine.ai_analyzer import generate_rca


def build_rca_report(incident_dict: dict, events: list) -> dict:
    clusters = correlate(events)
    anomalies = detect_anomalies(events, clusters)
    rca = generate_rca(incident_dict, clusters, anomalies)

    return {
        "incident": incident_dict,
        "clusters": clusters,
        "anomalies": anomalies,
        "rca": rca,
    }
