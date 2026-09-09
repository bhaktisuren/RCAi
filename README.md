# RCAi — Root Cause Analysis Intelligence

RCAi is a local, AI-powered incident investigation tool. It centralizes
data from CloudWatch, Site24x7, application logs, and manual notes,
correlates it into a timeline, detects anomalies, and generates a
structured Root Cause Analysis that clearly separates **confirmed
evidence** (traceable to actual data) from **AI inference** (the
model's reasoning).

This runs entirely on your machine — nothing is hosted externally
except the optional calls to the Anthropic API for AI reasoning, and
to AWS/Site24x7 if you configure live credentials.

---

## 1. Requirements

- Python 3.10+ (check with `python3 --version`)
- pip
- (Optional) An Anthropic API key for full AI-generated RCA narratives —
  get one at https://console.anthropic.com/. Without it, RCAi still
  works end-to-end using a rule-based fallback analyzer.

## 2. Setup

Open this folder in VS Code, then in the integrated terminal:

```bash
cd backend
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

Copy the environment template and fill in your keys:

```bash
cp .env.example .env
```

Open `.env` and set:
- `ANTHROPIC_API_KEY` — required for full AI-generated RCA reports
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` — optional, for live CloudWatch data
- `SITE24X7_API_KEY` / `SITE24X7_ACCOUNT_ID` — optional, for live Site24x7 data

If you leave the AWS/Site24x7 fields blank, those connectors
automatically return realistic **demo data** so you can try the full
workflow immediately.

## 3. Run it

```bash
python3 app.py
```

Then open **http://127.0.0.1:5000** in your browser.

## 4. Using RCAi

1. **Define incident** — name it, describe the symptom, set the time window.
2. **Collect evidence** — pull CloudWatch/Site24x7 data, upload a log/CSV/JSON
   file, or add a manual note. Everything lands in one normalized timeline.
3. **Correlate & detect** — click "Run correlation + generate AI root cause
   analysis." The engine groups events by time proximity, flags statistical
   anomalies, then sends that structured timeline to Claude for reasoning.
4. **RCA report** — review the generated report. Every field is editable
   in the browser. Confirmed evidence is tagged teal, AI inference is
   tagged amber. Click **Save edits**, then download as **PDF** (final,
   shareable) or **.docx** (fully editable in Word/Google Docs).

Reports and uploaded files are saved under `data/reports/` and
`data/uploads/` so nothing is lost between sessions.

## 5. Project structure

```
RCAi/
├── backend/
│   ├── app.py                    Flask app & all API routes
│   ├── requirements.txt
│   ├── .env.example              Copy to .env and fill in your keys
│   ├── models/incident.py        Event & Incident data classes
│   ├── connectors/                Pluggable data source connectors
│   │   ├── base_connector.py
│   │   ├── cloudwatch_connector.py
│   │   ├── site24x7_connector.py
│   │   └── log_parser.py
│   ├── engine/                    Correlation, anomaly detection, AI
│   │   ├── correlator.py
│   │   ├── anomaly_detector.py
│   │   ├── ai_analyzer.py
│   │   └── report_generator.py
│   └── exporters/                 PDF & DOCX report generation
│       ├── pdf_exporter.py
│       └── docx_exporter.py
├── frontend/
│   ├── templates/index.html
│   └── static/{css,js}
└── data/
    ├── sample_data/               Sample files to test uploads with
    ├── uploads/                   Your uploaded files land here
    └── reports/                   Generated reports & incident state
```

See **RCAi_Technical_Documentation.pdf** (in this same folder) for a
full explanation of how each piece works and how they connect.

## 6. Adding a new data source

To connect another monitoring tool (Datadog, PagerDuty, New Relic, etc.):

1. Create `backend/connectors/your_tool_connector.py`
2. Subclass `BaseConnector`, implement `fetch_events()` returning a list
   of `Event` objects (see `models/incident.py`)
3. Add a route in `app.py` similar to `/fetch/cloudwatch`
4. Add a card for it in `frontend/templates/index.html` and wire the
   button in `frontend/static/js/app.js`

Nothing else needs to change — the correlator, anomaly detector, and
AI analyzer all work on the normalized `Event` list regardless of source.
