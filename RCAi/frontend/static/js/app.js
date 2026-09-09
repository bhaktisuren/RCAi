/* ================================================================
   RCAi frontend logic
   Vanilla JS, no build step — open index.html via the Flask server
   and everything just works. Talks to the Flask API in backend/app.py.
   ================================================================ */

const API = "/api";
let CURRENT_INCIDENT = null;   // full incident object from backend
let CURRENT_REPORT = null;     // last generated RCA report

// ---------------- Utilities ----------------
function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show" + (isError ? " error" : "");
  setTimeout(() => el.classList.remove("show"), 3200);
}

function fmtTime(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return iso; }
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || "Request failed");
  }
  return res.json();
}

// ---------------- Step navigation ----------------
function goToStep(stepName) {
  document.querySelectorAll(".step").forEach(s => s.classList.toggle("active", s.dataset.step === stepName));
  document.querySelectorAll(".panel").forEach(p => p.classList.toggle("active", p.id === "panel-" + stepName));
}
document.querySelectorAll(".step").forEach(btn => {
  btn.addEventListener("click", () => {
    if (!CURRENT_INCIDENT && btn.dataset.step !== "setup") {
      toast("Create an investigation first", true);
      return;
    }
    goToStep(btn.dataset.step);
  });
});

// ---------------- Health check (sidebar status dots) ----------------
async function refreshHealth() {
  try {
    const h = await api("/health");
    setStatus("statusAI", h.ai_configured ? "on" : "demo", h.ai_configured ? "AI engine (Claude)" : "AI engine (fallback mode)");
    setStatus("statusCW", h.cloudwatch_configured ? "on" : "demo", h.cloudwatch_configured ? "CloudWatch (live)" : "CloudWatch (demo data)");
    setStatus("statusS247", h.site24x7_configured ? "on" : "demo", h.site24x7_configured ? "Site24x7 (live)" : "Site24x7 (demo data)");
    document.getElementById("cwModeLabel").textContent = h.cloudwatch_configured ? "live" : "demo mode";
    document.getElementById("s247ModeLabel").textContent = h.site24x7_configured ? "live" : "demo mode";
  } catch { /* backend not up yet */ }
}
function setStatus(id, state, label) {
  const row = document.getElementById(id);
  row.innerHTML = `<span class="dot dot-${state}"></span> ${escapeHtmlSafe(label)}`;
}
function escapeHtmlSafe(str) {
  const d = document.createElement("div");
  d.textContent = str ?? "";
  return d.innerHTML;
}

// ---------------- Incident list (sidebar) ----------------
async function refreshIncidentList() {
  try {
    const list = await api("/incidents");
    const el = document.getElementById("incidentList");
    if (!list.length) { el.innerHTML = '<div class="empty-hint">No investigations yet</div>'; return; }
    el.innerHTML = "";
    list.forEach(inc => {
      const div = document.createElement("div");
      div.className = "incident-item" + (CURRENT_INCIDENT && CURRENT_INCIDENT.incident_id === inc.incident_id ? " active" : "");
      div.innerHTML = `<div class="inc-title">${escapeHtml(inc.title)}</div><div class="inc-meta">${inc.incident_id}${inc.has_rca ? " · RCA ready" : ""}</div>`;
      div.addEventListener("click", () => loadIncident(inc.incident_id));
      el.appendChild(div);
    });
  } catch { /* ignore */ }
}

async function loadIncident(id) {
  const inc = await api(`/incidents/${id}`);
  CURRENT_INCIDENT = inc;
  renderEvents();
  if (inc.rca_report) {
    CURRENT_REPORT = inc.rca_report;
    renderReport(inc.rca_report);
    renderClustersAnomalies(inc.rca_report.clusters, inc.rca_report.anomalies);
  }
  refreshIncidentList();
  goToStep("ingest");
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str ?? "";
  return d.innerHTML;
}

// ---------------- Step 1: create incident ----------------
const now = new Date();
const anHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
function toLocalInput(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
document.querySelector('[name="start_time"]').value = toLocalInput(anHourAgo);
document.querySelector('[name="end_time"]').value = toLocalInput(now);

document.getElementById("incidentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  payload.start_time = new Date(payload.start_time).toISOString();
  payload.end_time = new Date(payload.end_time).toISOString();
  try {
    const inc = await api("/incidents", { method: "POST", body: JSON.stringify(payload) });
    CURRENT_INCIDENT = inc;
    CURRENT_REPORT = null;
    renderEvents();
    toast("Investigation created: " + inc.incident_id);
    refreshIncidentList();
    goToStep("ingest");
  } catch (err) { toast(err.message, true); }
});

document.getElementById("newIncidentBtn").addEventListener("click", () => {
  CURRENT_INCIDENT = null;
  CURRENT_REPORT = null;
  document.getElementById("incidentForm").reset();
  document.querySelector('[name="start_time"]').value = toLocalInput(anHourAgo);
  document.querySelector('[name="end_time"]').value = toLocalInput(now);
  goToStep("setup");
});

// ---------------- Step 2: ingest ----------------
function renderEvents() {
  const events = (CURRENT_INCIDENT && CURRENT_INCIDENT.events) || [];
  document.getElementById("eventCount").textContent = events.length;
  const tbody = document.querySelector("#eventTable tbody");
  if (!events.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-hint">No events collected yet</td></tr>';
    return;
  }
  const sorted = [...events].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
  tbody.innerHTML = sorted.map(e => `
    <tr>
      <td class="mono">${fmtTime(e.timestamp)}</td>
      <td>${escapeHtml(e.source)}</td>
      <td><span class="sev-badge sev-${e.severity}">${e.severity}</span></td>
      <td>${escapeHtml(e.message)}</td>
      <td class="mono">${escapeHtml(e.resource || "—")}</td>
    </tr>`).join("");
}

function requireIncident() {
  if (!CURRENT_INCIDENT) { toast("Create an investigation first", true); return false; }
  return true;
}

document.getElementById("fetchCW").addEventListener("click", async () => {
  if (!requireIncident()) return;
  try {
    const r = await api(`/incidents/${CURRENT_INCIDENT.incident_id}/fetch/cloudwatch`, { method: "POST", body: JSON.stringify({}) });
    CURRENT_INCIDENT.events.push(...r.events);
    renderEvents();
    toast(`Fetched ${r.added} CloudWatch event(s)${r.is_demo_mode ? " (demo data)" : ""}`);
  } catch (err) { toast(err.message, true); }
});

document.getElementById("fetchS247").addEventListener("click", async () => {
  if (!requireIncident()) return;
  try {
    const r = await api(`/incidents/${CURRENT_INCIDENT.incident_id}/fetch/site24x7`, { method: "POST", body: JSON.stringify({}) });
    CURRENT_INCIDENT.events.push(...r.events);
    renderEvents();
    toast(`Fetched ${r.added} Site24x7 event(s)${r.is_demo_mode ? " (demo data)" : ""}`);
  } catch (err) { toast(err.message, true); }
});

document.getElementById("uploadBtn").addEventListener("click", () => {
  if (!requireIncident()) return;
  document.getElementById("fileInput").click();
});
document.getElementById("fileInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const r = await fetch(`${API}/incidents/${CURRENT_INCIDENT.incident_id}/upload`, { method: "POST", body: fd });
    const data = await r.json();
    if (!r.ok) throw new Error(data.error);
    CURRENT_INCIDENT.events.push(...data.events);
    renderEvents();
    toast(`Parsed ${data.added} event(s) from ${data.filename}`);
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});

document.getElementById("manualBtn").addEventListener("click", async () => {
  if (!requireIncident()) return;
  const message = prompt("Describe what you observed:");
  if (!message) return;
  const severity = (prompt("Severity (info / warning / error / critical):", "info") || "info").toLowerCase();
  try {
    const ev = await api(`/incidents/${CURRENT_INCIDENT.incident_id}/manual-event`, {
      method: "POST", body: JSON.stringify({ message, severity, source: "Manual" }),
    });
    CURRENT_INCIDENT.events.push(ev);
    renderEvents();
    toast("Manual event added");
  } catch (err) { toast(err.message, true); }
});

document.getElementById("goToAnalyze").addEventListener("click", () => {
  if (!requireIncident()) return;
  if (!CURRENT_INCIDENT.events.length) { toast("Collect at least one event first", true); return; }
  goToStep("analyze");
});

// ---------------- Step 3: analyze ----------------
document.getElementById("runAnalysis").addEventListener("click", async () => {
  if (!requireIncident()) return;
  const btn = document.getElementById("runAnalysis");
  btn.disabled = true;
  btn.textContent = "Correlating events and generating RCA…";
  try {
    const report = await api(`/incidents/${CURRENT_INCIDENT.incident_id}/generate-rca`, { method: "POST" });
    CURRENT_REPORT = report;
    document.getElementById("analyzeEmpty").classList.add("hidden");
    document.getElementById("analyzeResults").classList.remove("hidden");
    renderClustersAnomalies(report.clusters, report.anomalies);
    renderReport(report);
    refreshIncidentList();
    toast("RCA generated");
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run correlation + generate AI root cause analysis";
  }
});

function renderClustersAnomalies(clusters, anomalies) {
  document.getElementById("analyzeEmpty").classList.add("hidden");
  document.getElementById("analyzeResults").classList.remove("hidden");
  document.getElementById("clusterCount").textContent = clusters.length;
  document.getElementById("anomalyCount").textContent = anomalies.length;

  document.getElementById("clusterList").innerHTML = clusters.map(c => `
    <div class="cluster-card">
      <div class="cluster-card-head">
        <span class="cid">Cluster #${c.cluster_id} · <span class="sev-badge sev-${c.max_severity}">${c.max_severity}</span></span>
        <span class="times">${fmtTime(c.start_time)} → ${fmtTime(c.end_time)}</span>
      </div>
      <div>${c.event_count} event(s)</div>
      <div class="cluster-sources">${c.sources.map(s => `<span class="source-chip">${escapeHtml(s)}</span>`).join("")}</div>
    </div>`).join("") || '<div class="empty-hint">No clusters</div>';

  document.getElementById("anomalyList").innerHTML = anomalies.map(a => `
    <div class="anomaly-card">
      <span class="anomaly-type">${escapeHtml(a.type)}</span>
      <div>${escapeHtml(a.explanation || "")}</div>
    </div>`).join("") || '<div class="empty-hint">No anomalies flagged</div>';
}

document.getElementById("goToReport").addEventListener("click", () => goToStep("report"));

// ---------------- Step 4: report ----------------
function renderReport(report) {
  const rca = report.rca || {};
  document.getElementById("reportEmpty").classList.add("hidden");
  document.getElementById("reportBody").classList.remove("hidden");

  document.getElementById("f_summary").textContent = rca.executive_summary || "";

  const rc = rca.root_cause || {};
  document.getElementById("f_rc_statement").textContent = rc.statement || "";
  document.getElementById("f_rc_confidence").value = rc.confidence || "Medium";
  document.getElementById("f_rc_reasoning").textContent = rc.reasoning || "";

  const evTbody = document.querySelector("#f_evidence_table tbody");
  evTbody.innerHTML = (rca.confirmed_evidence || []).map(ev => `
    <tr><td contenteditable="true">${escapeHtml(ev.finding)}</td><td contenteditable="true" class="mono">${escapeHtml(ev.source_reference)}</td></tr>
  `).join("") || '<tr><td colspan="2" class="empty-hint">No confirmed evidence returned</td></tr>';

  document.getElementById("f_factors_list").innerHTML = (rca.contributing_factors || []).map(cf => {
    const isEvidence = String(cf.type || "").toLowerCase().includes("confirmed");
    return `<div class="factor-row" data-type="${isEvidence ? 'confirmed_evidence' : 'ai_inference'}">
      <span class="tag-pill ${isEvidence ? 'evidence' : 'inference'}">${isEvidence ? 'Evidence' : 'Inference'}</span>
      <div contenteditable="true" style="flex:1">${escapeHtml(cf.factor)} — ${escapeHtml(cf.detail || "")}</div>
    </div>`;
  }).join("") || '<div class="empty-hint">None listed</div>';

  const impact = rca.incident_impact || {};
  document.getElementById("f_impact_summary").textContent = impact.summary || "";
  document.getElementById("f_impact_systems").textContent = (impact.affected_systems || []).join(", ");
  document.getElementById("f_impact_duration").textContent = impact.estimated_duration || "";
  document.getElementById("f_impact_user").textContent = impact.user_impact || "";

  document.getElementById("f_resolution_list").innerHTML = (rca.resolution_actions || []).map(a => `
    <div class="action-row">
      <span class="tag-pill priority-${(a.priority||'').toLowerCase().replace(/\s+/g,'-')}">${escapeHtml(a.priority || "")}</span>
      <div contenteditable="true" style="flex:1">${escapeHtml(a.action)}</div>
    </div>`).join("") || '<div class="empty-hint">None listed</div>';

  document.getElementById("f_preventive_list").innerHTML = (rca.preventive_actions || []).map(a => `
    <div class="action-row">
      <span class="tag-pill evidence">${escapeHtml(a.category || "")}</span>
      <div contenteditable="true" style="flex:1">${escapeHtml(a.action)}</div>
    </div>`).join("") || '<div class="empty-hint">None listed</div>';

  document.getElementById("f_narrative").textContent = rca.timeline_narrative || "";
}

function collectEditedRca() {
  const original = (CURRENT_REPORT && CURRENT_REPORT.rca) || {};
  const evidenceRows = [...document.querySelectorAll("#f_evidence_table tbody tr")].map(tr => {
    const cells = tr.querySelectorAll("td");
    if (cells.length < 2) return null;
    return { finding: cells[0].textContent.trim(), source_reference: cells[1].textContent.trim() };
  }).filter(Boolean);

  const factorRows = [...document.querySelectorAll("#f_factors_list .factor-row")].map(row => ({
    factor: row.querySelector("div").textContent.trim(),
    type: row.dataset.type,
    detail: "",
  }));

  const resolutionRows = [...document.querySelectorAll("#f_resolution_list .action-row")].map(row => ({
    action: row.querySelector("div").textContent.trim(),
    priority: row.querySelector(".tag-pill").textContent.trim(),
  }));

  const preventiveRows = [...document.querySelectorAll("#f_preventive_list .action-row")].map(row => ({
    action: row.querySelector("div").textContent.trim(),
    category: row.querySelector(".tag-pill").textContent.trim(),
  }));

  return {
    ...original,
    executive_summary: document.getElementById("f_summary").textContent.trim(),
    root_cause: {
      ...(original.root_cause || {}),
      statement: document.getElementById("f_rc_statement").textContent.trim(),
      confidence: document.getElementById("f_rc_confidence").value,
      reasoning: document.getElementById("f_rc_reasoning").textContent.trim(),
      type: "ai_inference",
    },
    confirmed_evidence: evidenceRows,
    contributing_factors: factorRows,
    incident_impact: {
      summary: document.getElementById("f_impact_summary").textContent.trim(),
      affected_systems: document.getElementById("f_impact_systems").textContent.split(",").map(s => s.trim()).filter(Boolean),
      estimated_duration: document.getElementById("f_impact_duration").textContent.trim(),
      user_impact: document.getElementById("f_impact_user").textContent.trim(),
    },
    resolution_actions: resolutionRows,
    preventive_actions: preventiveRows,
    timeline_narrative: document.getElementById("f_narrative").textContent.trim(),
  };
}

document.getElementById("saveEditsBtn").addEventListener("click", async () => {
  if (!requireIncident() || !CURRENT_REPORT) return;
  try {
    const rca = collectEditedRca();
    const updated = await api(`/incidents/${CURRENT_INCIDENT.incident_id}/rca`, { method: "PUT", body: JSON.stringify({ rca }) });
    CURRENT_REPORT = updated;
    toast("Edits saved");
  } catch (err) { toast(err.message, true); }
});

async function exportReport(fmt) {
  if (!requireIncident() || !CURRENT_REPORT) { toast("Generate a report first", true); return; }
  try {
    // Persist any unsaved edits before exporting
    const rca = collectEditedRca();
    await api(`/incidents/${CURRENT_INCIDENT.incident_id}/rca`, { method: "PUT", body: JSON.stringify({ rca }) });
    window.location.href = `${API}/incidents/${CURRENT_INCIDENT.incident_id}/export/${fmt}`;
  } catch (err) { toast(err.message, true); }
}
document.getElementById("exportPdf").addEventListener("click", () => exportReport("pdf"));
document.getElementById("exportDocx").addEventListener("click", () => exportReport("docx"));

// ---------------- Init ----------------
refreshHealth();
refreshIncidentList();
