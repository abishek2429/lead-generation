# IncuBrix Multi-Channel Lead Generation Engine
## Day 2 — Lead Discovery & Qualification Foundation

A production-grade, testable creator discovery and qualification engine built for the IncuBrix Growth Engineer Assessment (Option 1). It implements multi-channel candidate discovery, deterministic deduplication by canonical profile URLs and stable platform IDs, non-negotiable policy hard gates, weighted multi-attribute scoring, SQLite persistence with complete verification audit trails, and an interactive Streamlit operations dashboard.

---

## 🚀 Key Highlights & Day 2 Acceptance Criteria Met

1. **Automatic Database Initialization**: SQLite repository (`data/database/leads.db`) auto-creates relational tables, indexes, and audit logs upon first startup.
2. **Strict Candidate vs. Qualified Lead Separation**: Newly discovered candidates always enter the pipeline in `discovered` status. A candidate is **never** assumed to be qualified without explicit verification.
3. **Deterministic Deduplication & Merging**: Matches candidates by normalized platform key `(platform, platform_id)` or canonical profile URL (stripping tracking parameters like `utm_*`, `si`, `fbclid`). Merges new evidence deterministically into existing records while preserving the earliest discovery timestamp.
4. **Day 1 Qualification Policy Hard Gates**: Unit-tested enforcement of 10 non-negotiable gates:
   - Creator segment fit (allowed vs. excluded agency/fan/directory accounts)
   - 7 approved geographies (United States, Canada, UK, Ireland, Australia, New Zealand, Singapore)
   - Primary language (English)
   - Stable platform ID & canonical profile URL
   - Verified commercial evidence URL (course, coaching, sponsor, membership)
   - Verified workflow need evidence URL (repurposing backlog, multi-platform friction)
   - Public business contact (verified value, channel type, source URL; no guessed emails)
   - Contact recency (active within 60 days)
   - Publishing activity threshold (≥8 items in 30 days OR ≥2 long-form items in 60 days)
   - Evidence freshness window (verified within 30 days)
5. **Weighted Scoring & Priority Tiers**: Evaluates qualified leads across 5 weighted dimensions (Workflow Need: 30, Segment Fit: 25, Commercial Intent: 20, Publishing Consistency: 15, Contact Quality: 10). Assigns Priority A, B, or C.
6. **Assessment Deliverables Export**: Generates workbook-ready deliverables with exact column headers:
   - `data/output/qualified_leads.csv` — Verified creators passing all gates with evidence links
   - `data/output/all_candidates.csv` — Full discovery register with status tracking
   - `data/output/disqualification_audit.csv` — Transparent log of rejected candidates with failure reasons
   - `data/output/summary_report.json` — Machine-readable metrics breakdown
7. **Zero Fabricated Data**: Missing evidence is strictly represented as `None`/empty, never guessed or synthesized.
8. **100% Passing Test Suite**: 29 automated pytest unit and end-to-end integration tests.

---

## 📁 Repository Structure

```text
lead-generation/
├── app.py                      # Interactive Streamlit operations dashboard
├── src/
│   ├── config.py               # Configuration loader & qualification policy parser
│   ├── models.py               # Pydantic v2 data models (Lead, VerificationLog)
│   ├── database.py             # SQLite repository & schema auto-initialization
│   ├── deduplication.py        # Canonical URL normalization & deterministic merge logic
│   ├── exports.py              # Workbook-compliant CSV and JSON export engine
│   ├── logging_config.py       # Structured logging with UTC timestamps & run IDs
│   ├── discovery/
│   │   ├── base.py             # Abstract base class for discovery adapters
│   │   ├── import_csv.py       # Resilient CSV parser with flexible header mapping
│   │   └── youtube_api.py      # Compliant YouTube Data API v3 discovery client
│   └── verification/
│       ├── evidence.py         # URL, date, and gate validation helpers
│       └── qualification.py    # Hard gates evaluator, scoring rubric, and country mix validator
├── data/
│   ├── input/
│   │   └── candidates_sample.csv   # Benchmark candidate dataset (qualified & test rejection cases)
│   ├── output/                 # Exported deliverables (qualified, candidates, audit, JSON)
│   └── database/               # SQLite database location (leads.db)
├── tests/
│   ├── test_models.py          # Model validation & serialization tests
│   ├── test_database.py        # Database operations & audit log tests
│   ├── test_deduplication.py   # Canonicalization & merge unit tests
│   ├── test_qualification.py   # Hard gate, scoring, and country mix tests
│   ├── test_csv_import.py      # CSV parser & alias mapping tests
│   ├── test_exports.py         # Assessment workbook header compliance tests
│   └── test_e2e_pipeline.py    # Complete lifecycle integration test
├── config/
│   └── qualification_config.json # Machine-readable qualification gates & weights
├── qualification_config.json   # Root copy preserved for Day 1 backward compatibility
├── growth_opportunities.csv    # Day 1 research growth opportunities
├── sources.csv                 # Day 1 research sources register
├── market_and_competitor_evidence.csv # Day 1 research market evidence
├── requirements.txt            # Python dependencies
├── .env.example                # Environment configuration template
├── .gitignore                  # Git ignore rules (protects databases, secrets, logs)
└── README.md                   # This documentation
```

---

## 🛠️ Windows PowerShell Setup Guide

Follow these exact steps from a fresh installation on Windows using PowerShell:

### 1. Open Windows PowerShell in Project Root
```powershell
Set-Location -Path "C:\lead-generation"
```

### 2. Verify Python Installation
Python 3.11+ or 3.12+ is supported:
```powershell
python --version
```

### 3. Create and Activate Virtual Environment (Recommended)
```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 4. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 5. Initialize Environment File
```powershell
Copy-Item .env.example .env
```
*(Optional: If you wish to use live YouTube Channel search, open `.env` and add your Google API key under `YOUTUBE_API_KEY`. Live discovery is optional; CSV discovery works fully offline without any API keys).*

---

## 🧪 Running the Automated Test Suite

Run the full pytest suite with a single command:

```powershell
pytest -v
```

Expected output:
```text
============================= test session starts =============================
platform win32 -- Python 3.11.5, pytest-9.1.1, pluggy-1.7.0
rootdir: C:\lead-generation
collected 29 items

tests/test_csv_import.py::test_csv_import_standard_headers PASSED        [  3%]
tests/test_csv_import.py::test_csv_import_flexible_aliases PASSED        [  6%]
tests/test_csv_import.py::test_csv_import_missing_mandatory_columns PASSED [ 10%]
tests/test_database.py::test_database_auto_initialization PASSED         [ 13%]
tests/test_database.py::test_insert_and_get_lead PASSED                  [ 17%]
tests/test_database.py::test_update_lead PASSED                          [ 20%]
tests/test_database.py::test_verification_audit_log PASSED               [ 24%]
tests/test_database.py::test_database_metrics PASSED                     [ 27%]
tests/test_deduplication.py::test_canonicalize_url_cleanups PASSED       [ 31%]
tests/test_deduplication.py::test_merge_leads_deterministic PASSED       [ 34%]
tests/test_deduplication.py::test_deduplicate_batch_by_platform_and_canonical_url PASSED [ 37%]
tests/test_e2e_pipeline.py::test_full_day2_lifecycle PASSED              [ 41%]
tests/test_exports.py::test_export_workbook_headers_match PASSED         [ 44%]
tests/test_exports.py::test_export_filters_candidates_vs_qualified PASSED [ 48%]
tests/test_exports.py::test_export_workbook_pack PASSED                  [ 51%]
tests/test_models.py::test_lead_initialization_defaults PASSED           [ 55%]
tests/test_models.py::test_lead_empty_strings_convert_to_none PASSED     [ 58%]
tests/test_models.py::test_lead_list_field_parsing PASSED                [ 62%]
tests/test_models.py::test_db_serialization_roundtrip PASSED             [ 65%]
tests/test_qualification.py::test_valid_lead_passes_all_hard_gates PASSED [ 68%]
tests/test_qualification.py::test_segment_gate_rejections PASSED         [ 72%]
tests/test_country_gate_rejections PASSED                                [ 75%]
tests/test_qualification.py::test_language_gate_rejections PASSED        [ 79%]
tests/test_qualification.py::test_evidence_gate_rejections PASSED        [ 82%]
tests/test_qualification.py::test_business_contact_gate_rejections PASSED [ 86%]
tests/test_qualification.py::test_activity_gate_rejections PASSED        [ 89%]
tests/test_qualification.py::test_evidence_freshness_gate_rejections PASSED [ 93%]
tests/test_qualification.py::test_full_qualify_lead_flow PASSED          [ 96%]
tests/test_qualification.py::test_country_mix_validation PASSED          [100%]

============================= 29 passed in 0.67s ==============================
```

---

## 🖥️ Running the Streamlit Application

Launch the operations dashboard with:

```powershell
streamlit run app.py
```
Open your browser to: **`http://localhost:8501`**

### Dashboard Feature Tour:
1. **📊 Pool Overview & Mix**:
   - Real-time KPI summary (Total Candidates, Pending Review, Qualified Leads, Disqualified, Priority A Count).
   - Geographic distribution breakdown validated against Day 1 policy targets (≥80% approved geographies, ≥3 distinct countries, ≤60% max single-country concentration).
2. **📥 Candidate Discovery (CSV & API)**:
   - Import candidates from `data/input/candidates_sample.csv` or upload a custom CSV.
   - Preview records before saving.
   - Execute deterministic deduplication and database merge with one click.
   - Live YouTube Data API v3 channel discovery (if API key provided).
3. **⚖️ Qualification Engine & Gates**:
   - Batch evaluation pipeline assessing pending or all candidates against all 10 hard gates.
   - Gate-by-gate inspector showing exact pass/fail reasons and weighted scoring breakdown for any creator.
   - Real-time audit log of all verification events.
4. **🔍 Lead & Evidence Inspector**:
   - Filterable candidate registry (filter by status, priority tier, country, or keyword search).
   - Clickable links for official profiles, commercial offers, workflow evidence, and verified contact channels.
5. **📤 Assessment Exports & Deliverables**:
   - Generate all 4 workbook-compliant deliverables into `data/output/` with one click.
   - Direct in-browser download buttons for `qualified_leads.csv`, `all_candidates.csv`, `disqualification_audit.csv`, and `summary_report.json`.

---

## 📋 Data Model Specification

Every lead record follows this strict Pydantic model (`src/models.py`):

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `creator_name` | `str` | Full creator or channel name |
| `creator_type` | `str` | Creator segment (e.g. `video_podcaster`, `coach_creator`) |
| `country` | `Optional[str]` | Creator country (one of 7 approved geographies) |
| `language` | `Optional[str]` | Content language (defaults to `English`) |
| `platform` | `str` | Primary platform (`youtube`, `podcast`, etc.) |
| `platform_id` | `str` | Stable channel ID (`UC...`) or slug |
| `official_profile_url` | `str` | Canonical profile URL |
| `candidate_source_url` | `str` | URL where candidate was discovered |
| `recent_content_urls` | `List[str]` | Recent video/episode links |
| `recent_content_dates` | `List[str]` | ISO upload dates (`YYYY-MM-DD`) |
| `commercial_evidence_url` | `Optional[str]` | Link to course, coaching, sponsorship, or booking offer |
| `workflow_need_evidence_url` | `Optional[str]` | Evidence of repurposing backlog or multi-platform friction |
| `business_contact_type` | `Optional[str]` | Channel type (`email`, `form`, `social_dm`) |
| `business_contact_value` | `Optional[str]` | Verified public contact value |
| `business_contact_source_url` | `Optional[str]` | Public page where contact was found |
| `business_contact_last_active` | `Optional[str]` | Last activity date (`YYYY-MM-DD`) |
| `evidence_checked_at` | `Optional[str]` | ISO timestamp when evidence was verified |
| `qualification_status` | `str` | `'discovered'`, `'qualified'`, or `'disqualified'` |
| `disqualification_reasons` | `List[str]` | Explicit failure reasons if disqualified |
| `score` | `float` | Weighted score from 0.0 to 100.0 |
| `priority` | `Optional[str]` | Priority tier (`'A'`, `'B'`, `'C'`, or `None`) |
| `first_discovered_at` | `str` | Earliest discovery ISO timestamp |
| `last_checked_at` | `Optional[str]` | Most recent evaluation ISO timestamp |
| `last_run_id` | `Optional[str]` | Unique run identifier for auditability |

---

## 🛡️ Compliance & Ethical Boundaries

In strict compliance with the Day 1 research policy and Day 2 requirements:
- **No Scraping Against Terms**: No unauthorized scraping of LinkedIn, YouTube, or private sites.
- **Permitted Public APIs Only**: Uses official YouTube Data API v3 and public creator websites.
- **Zero Guessed Emails**: Contacts must have a public source verification URL. Guessed email addresses are strictly rejected by hard gates.
- **No Outreach to Real Creators**: Outreach actions are prevented during the assessment.
- **No API Keys in Version Control**: API keys are isolated in `.env` and excluded via `.gitignore`.
