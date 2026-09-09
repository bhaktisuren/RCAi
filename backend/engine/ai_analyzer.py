"""
engine/ai_analyzer.py
------------------------
This is the "AI" in RCAi. It does NOT let the model freely write an RCA
from vague memory - it feeds the model the exact correlated events and
detected anomalies produced by the deterministic engine (correlator.py +
anomaly_detector.py), and forces it to return structured JSON that keeps
"confirmed_evidence" (directly traceable to an event/anomaly we fed it)
strictly separate from "ai_inference" (the model's reasoning/hypothesis).

If no ANTHROPIC_API_KEY is configured, a rule-based fallback analyzer
produces a best-effort structured report so the app still works end to
end in demo mode.
"""

import os
import json
import re

SYSTEM_PROMPT = """You are RCAi, a senior Site Reliability Engineer performing Root Cause Analysis.
You will be given:
1. Incident metadata (title, description, time window)
2. A correlated timeline of events pulled from monitoring tools (CloudWatch, Site24x7, application logs)
3. A list of anomalies already detected by a deterministic statistical engine

Your job is to produce a structured Root Cause Analysis. You MUST separate:
- "confirmed_evidence": facts that are directly and explicitly present in the timeline/anomalies you were given.
  Every confirmed_evidence item MUST reference the specific event(s)/anomaly it comes from.
- "ai_inference": your own reasoning, hypotheses, or conclusions that go beyond what is
  literally stated in the data (causal links, likely triggers, judgment calls).
Never present an inference as if it were confirmed evidence, and never invent events that
were not given to you.

Respond with ONLY valid JSON (no markdown fences, no commentary) in exactly this schema:

{
  "executive_summary": "2-4 sentence plain-English summary of what happened",
  "confirmed_evidence": [
    {"finding": "...", "source_reference": "e.g. Cluster #2 / CloudWatch CPUUtilization event at <timestamp>"}
  ],
  "root_cause": {
    "statement": "single clear root cause statement",
    "confidence": "High | Medium | Low",
    "reasoning": "explanation of how the evidence leads to this conclusion",
    "type": "ai_inference"
  },
  "contributing_factors": [
    {"factor": "...", "type": "confirmed_evidence | ai_inference", "detail": "..."}
  ],
  "incident_impact": {
    "summary": "...",
    "affected_systems": ["..."],
    "estimated_duration": "...",
    "user_impact": "..."
  },
  "resolution_actions": [
    {"action": "...", "priority": "Immediate | Short-term | Long-term"}
  ],
  "preventive_actions": [
    {"action": "...", "category": "Monitoring | Architecture | Process | Capacity"}
  ],
  "timeline_narrative": "chronological plain-English walkthrough of the incident referencing timestamps"
}
"""


def _build_user_prompt(incident: dict, clusters: list, anomalies: list) -> str:
    payload = {
        "incident": {
            "title": incident.get("title"),
            "description": incident.get("description"),
            "start_time": incident.get("start_time"),
            "end_time": incident.get("end_time"),
        },
        "correlated_clusters": clusters,
        "detected_anomalies": anomalies,
    }
    return (
        "Analyze the following incident data and return the RCA JSON as instructed.\n\n"
        + json.dumps(payload, indent=2, default=str)
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def generate_rca_with_claude(incident: dict, clusters: list, anomalies: list) -> dict:
    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    client = Anthropic(api_key=api_key)

    user_prompt = _build_user_prompt(incident, clusters, anomalies)

    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    full_text = "\n".join(text_blocks)
    return _extract_json(full_text)


def generate_rca_fallback(incident: dict, clusters: list, anomalies: list) -> dict:
    """Rule-based fallback used when no ANTHROPIC_API_KEY is configured.
    Produces a genuinely structured, evidence-linked report - just without
    the natural-language reasoning an LLM would add."""

    confirmed = []
    for c in clusters:
        confirmed.append({
            "finding": f"{c['event_count']} event(s) from {', '.join(c['sources'])} between "
                       f"{c['start_time']} and {c['end_time']}, peak severity '{c['max_severity']}'.",
            "source_reference": f"Cluster #{c['cluster_id']}",
        })
    for a in anomalies:
        confirmed.append({
            "finding": a.get("explanation", str(a)),
            "source_reference": f"Anomaly type: {a.get('type')}",
        })

    highest_cluster = max(clusters, key=lambda c: c["event_count"], default=None)
    root_cause_statement = (
        f"Most probable trigger correlates with cluster #{highest_cluster['cluster_id']} "
        f"({', '.join(highest_cluster['sources'])}) which had the highest event concentration."
        if highest_cluster else
        "Insufficient correlated data to isolate a single root cause automatically."
    )

    return {
        "executive_summary": f"Automated (non-AI fallback) analysis of '{incident.get('title')}' "
                              f"correlated {len(clusters)} event cluster(s) and {len(anomalies)} anomaly signal(s). "
                              f"Configure ANTHROPIC_API_KEY for a full natural-language AI-generated RCA.",
        "confirmed_evidence": confirmed,
        "root_cause": {
            "statement": root_cause_statement,
            "confidence": "Low",
            "reasoning": "Derived heuristically from event density only; no LLM reasoning was applied. "
                         "This is a fallback report - add an API key for deeper causal analysis.",
            "type": "ai_inference",
        },
        "contributing_factors": [
            {"factor": a.get("explanation", str(a)), "type": "confirmed_evidence", "detail": a.get("type", "")}
            for a in anomalies[:5]
        ],
        "incident_impact": {
            "summary": "Impact summary requires AI analysis - configure ANTHROPIC_API_KEY for full detail.",
            "affected_systems": sorted(set(s for c in clusters for s in c["sources"])),
            "estimated_duration": f"{clusters[0]['start_time']} to {clusters[-1]['end_time']}" if clusters else "Unknown",
            "user_impact": "Not automatically determined in fallback mode.",
        },
        "resolution_actions": [
            {"action": "Review the highest-severity cluster manually and confirm root cause.", "priority": "Immediate"}
        ],
        "preventive_actions": [
            {"action": "Configure ANTHROPIC_API_KEY to enable full AI-generated preventive recommendations.",
             "category": "Process"}
        ],
        "timeline_narrative": " -> ".join(
            f"[{c['start_time']}] {c['event_count']} event(s) ({c['max_severity']})" for c in clusters
        ),
    }


def generate_rca(incident: dict, clusters: list, anomalies: list) -> dict:
    """Main entry point. Uses Claude if configured, otherwise the fallback."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return generate_rca_with_claude(incident, clusters, anomalies)
        except Exception as e:
            fallback = generate_rca_fallback(incident, clusters, anomalies)
            fallback["ai_error"] = f"AI generation failed, showing fallback analysis instead: {e}"
            return fallback
    return generate_rca_fallback(incident, clusters, anomalies)
