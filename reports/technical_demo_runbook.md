# IncuBrix Technical Demonstration Runbook (8-Minute Live Walkthrough)

**IncuBrix Multi-Channel Lead Generation & Outreach Engine**  
**Enterprise Operations Edition — Technical Architecture & Pipeline Demo**  
**Document:** `reports/technical_demo_runbook.md`  
**Target Duration:** Strictly 8 Minutes (0:00 – 8:00)  
**Presenter:** Senior Growth Engineer / Lead System Architect  
**Environment:** Windows 11 (64-bit), Python 3.11.5, PowerShell Core / Windows PowerShell 5.1  
**Operating Philosophy:** Live Application Demonstration • Real Code & UI Execution • Zero Narrated Slide Decks • Zero Fabricated Metrics  

---

## Technical Demo Overview & Timing Breakdown

| Segment | Timecode | Focus Area | Interface Shown |
| :---: | :---: | :--- | :--- |
| **1** | **0:00 – 1:00** | System Architecture & Decoupled Pipeline | Terminal (Project Tree) & Codebase Structure |
| **2** | **1:00 – 2:30** | Normal Execution & Candidate Discovery | Streamlit UI (Tab 2: Discovery) |
| **3** | **2:30 – 4:00** | Qualification Policy & Evidence Audit | Streamlit UI (Tab 3: Qualification & Tab 4: Evidence) |
| **4** | **4:00 – 5:15** | Deduplication Engine & Repeat Idempotency | Streamlit UI (Tab 2) & PowerShell Output |
| **5** | **5:15 – 6:30** | Production Deliverables Export & Outreach Prep | Streamlit UI (Tab 8: CRM Sync & Tab 5: Outreach) |
| **6** | **6:30 – 7:30** | Controlled Failure Recovery & Circuit Breakers | Terminal & UI Sandbox (API Quota, Malformed CSV, SSRF) |
| **7** | **7:30 – 8:00** | Empirical Results, Scale Benchmarks & Boundaries | Terminal (`pytest -v`, Scale Metrics) & Wrap-Up |

---

## Pre-Demo Checklist & Workstation Preparation (T-minus 5 Minutes)

Run these preparatory verification commands in PowerShell before starting your screen recording or live presentation:

```powershell
# 1. Navigate to repository root
Set-Location -Path "C:\lead-generation"

# 2. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 3. Ensure test suite is completely green (101/101 tests pass)
pytest -q
# Expected output: 101 passed in ~6.8s

# 4. Clean database to baseline state (11 synthetic fixtures, 7 qualified, 77 evidence items)
python -m scripts.run_audit_pipeline

# 5. Launch the Streamlit dashboard in a dedicated browser window
streamlit run app.py --server.port 8501
```

*Open browser at **`http://localhost:8501`** alongside your PowerShell terminal.*

---

## Segment-by-Segment Timed Script & Action Plan

---

### Segment 1: System Architecture & Data Flow (0:00 – 1:00)

#### Objective
Explain the modular, decoupled architecture of the IncuBrix engine. Prove that the application is cleanly structured with separation of concerns between discovery, deduplication, qualification, evidence verification, and outreach.

#### Visual / Interface
Show your code editor or PowerShell terminal displaying the directory tree:

```powershell
Get-ChildItem -Directory | Select-Object Name
```

#### Narration & Talking Points
> *"Hello, I'm presenting the technical demonstration for the IncuBrix Multi-Channel Lead Generation and Outreach Engine.  
> Rather than a static slide deck, this 8-minute demonstration executes the real application, its live Streamlit dashboard, SQLite database, and automated test suite.  
> 
> The architecture is strictly decoupled across five core layers:  
> 1. **Discovery Adapters (`src/discovery/`):** Standardizes offline CSV ingestion with flexible column aliasing, and implements an official YouTube Data API v3 client with graceful quota degradation. In accordance with platform terms, automated scrapers for LinkedIn and Instagram are strictly prohibited.  
> 2. **Deduplication Engine (`src/deduplication.py`):** Canonicalizes URLs by stripping session and tracking query parameters (`utm_*`, `ref`, `si`), indexes platform keys, and executes deterministic merges.  
> 3. **Persistence Layer (`src/database.py`):** SQLite 3 with Write-Ahead Logging (WAL) and single-transaction batch persistence, handling 5,000 records in 25 seconds.  
> 4. **Qualification & Evidence Engine (`src/verification/`):** Evaluates 10 non-negotiable hard gates, builds 7 source-linked evidence items per candidate with SSRF defense, and scores qualified leads across a 5-dimension rubric capped at 25 Priority A leads.  
> 5. **Outreach & Safe Seed Simulator (`src/verification/outreach.py`, `src/simulator_server.py`):** Selects primary/backup channels deterministically, crafts 3-touch grounded copy, and simulates tracking on internal test seed accounts only.  
> Let's look at the running system."*

#### Actions & Commands
- Point to the active Streamlit dashboard header: **"IncuBrix Lead Engine — Multi-Channel Outreach"**.
- Highlight the session run ID in the sidebar.

---

### Segment 2: Normal Run & Candidate Discovery (1:00 – 2:30)

#### Objective
Demonstrate candidate ingestion via the offline CSV discovery adapter, inspect processing counts, and verify the YouTube API integration status.

#### Visual / Interface
Switch to the browser at `http://localhost:8501`. Highlight the 6 metric cards at the top, then navigate to **Tab 2: 📥 Candidate Discovery (CSV & API)**.

#### Actions & Demonstration Steps
1. **Show Top Metric Cards:**
   - *Total Candidates:* `11 (11 fixtures)`
   - *Needs Review:* `1`
   - *Real Qualified:* `0` *(Transparently highlight that no real creator leads are fabricated)*
   - *Disqualified:* `3`
   - *Priority A Leads:* `7`
   - *Freshness Rate:* `100%`
2. **Review Sidebar Integration Status:**
   - Point out **`No API Key (CSV mode active)`** in the sidebar.
   - Mention: *"Because Google Cloud YouTube API quotas are limited to 10,000 units/day, the engine defaults to an offline-first CSV discovery mode, ensuring repeatable execution without external network dependencies."*
3. **Inspect Tab 2: Candidate Discovery:**
   - Under *Discovery Source Selection*, select **"CSV Ingestion & Normalisation"**.
   - Under *CSV Source Option*, select **"Use Default Fixture (data/input/candidates_sample.csv)"**.
   - Point to the table preview showing 11 parsed synthetic validation candidates across segments: `podcaster`, `video_podcaster`, `coach_creator`, `consultant_creator`, `educator_creator`, and `agency`.
4. **Demonstrate YouTube API Smoke Test:**
   - Toggle to **"Official YouTube Data API v3"** radio option.
   - Click the **"🧪 Run YouTube API Smoke Test"** button.
   - Expected message appears:
     > `ℹ️ YouTube Data API v3 key is not configured. To enable live discovery, set YOUTUBE_API_KEY in your .env file or system environment.`  
     > `Saved diagnostic report to data/output/youtube_api_smoke_test.json`
   - Explain: *"Notice that the application does not crash when an API key is unconfigured. It catches the state cleanly, writes a diagnostic report, and falls back to CSV mode."*

---

### Segment 3: Qualification Policy & Evidence Audit (2:30 – 4:00)

#### Objective
Demonstrate the 10 hard qualification gates, source-linked evidence generation, transparent scoring rubric, and why candidates with missing evidence are strictly routed to `needs_review`.

#### Visual / Interface
Navigate to **Tab 3: ⚖️ Qualification & Transparent Scoring**, then cross-reference with **Tab 4: 🔍 Source-Linked Evidence Inspector**.

#### Actions & Demonstration Steps
1. **Inspect a Fully Qualified Candidate:**
   - In Tab 3, scroll to **"🔬 Creator Gate Inspector"**.
   - In the dropdown *Select Creator to Inspect:*, select:  
     `[FIXTURE] The SaaS Breakout Show (UC_SAAS_BREAKOUT) [qualified]`.
   - Show Left Column:
     - Creator Segment: `video_podcaster` | Country: `United States` | Language: `English`
     - Status: `<span class="badge-qual">QUALIFIED (Score: 88.0 | Priority A)</span>`
     - Evidence links: Commercial (`https://saasbreakout.com/sponsor`), Workflow Need (`https://youtube.com/@saasbreakout/videos`), Contact (`business@saasbreakout.synthetic.test`).
   - Show Right Column (Gate-by-Gate Audit):
     - Display: `✅ All 10 Non-Negotiable Hard Gates Passed!`
     - Expand the **Transparent Scoring Breakdown (5 Dimensions)**:
       - Content Workflow Need: **30 / 30 pts**
       - Creator Segment Fit: **25 / 25 pts**
       - Commercial Intent: **20 / 20 pts**
       - Publishing Cadence: **8 / 15 pts**
       - Contact Quality: **5 / 10 pts**
       - Total: **88.0 / 100 pts**
2. **Demonstrate Missing Evidence Failure ("Needs Review"):**
   - In the dropdown, switch to:  
     `[FIXTURE] Unmonetized Tech Enthusiast (UC_UNMONETIZED) [needs_review]`.
   - Point to the Evidence Links:
     - Commercial: `*Missing*`
     - Workflow Need: `*Missing*`
   - Point to Gate Audit:
     > `⚠️ Flagged for Human Review: Missing commercial offer URL (Gate 5); Missing workflow need evidence URL (Gate 6)`
   - Narration: *"Here is a critical integrity rule: The engine never guesses or fabricates commercial intent. If proof URLs are missing, the candidate cannot pass to 'qualified'. It is classified as 'needs_review' for human verification."*
3. **Demonstrate Policy Disqualifications:**
   - In the dropdown, switch to:  
     `[FIXTURE] Apex Media Growth Agency (UC_APEX_MEDIA_AGY) [disqualified]`.
   - Point to Gate Failure: Disqualified by Gate 1 (Segment Exclusion: `'agency'` is an excluded business type).
   - In the dropdown, switch to:  
     `[FIXTURE] Berlin Creator Lounge (UC_BERLIN_CREATOR) [disqualified]`.
   - Point to Gate Failure: Disqualified by Gate 2 (Country Exclusion: `'Germany'` is outside the 7 approved English-speaking target geos).
4. **Inspect Source-Linked Evidence (Tab 4):**
   - Click **Tab 4: 🔍 Source-Linked Evidence Inspector**.
   - Filter by Creator: `[FIXTURE] The SaaS Breakout Show`.
   - Show all 7 verified evidence claims with checked timestamps, verification methods, and factual descriptions.

---

### Segment 4: Deduplication Engine & Repeat Idempotency (4:00 – 5:15)

#### Objective
Demonstrate that re-importing identical or overlapping candidate datasets prevents duplicate database records and maintains deterministic state reconciliation.

#### Visual / Interface
Switch to PowerShell terminal or Tab 2 in Streamlit.

#### Actions & Demonstration Steps
1. **Execute Duplicate Ingestion via PowerShell:**
   Run the deduplication verification command directly:

   ```powershell
   python -c "from src.database import Database; from src.deduplication import deduplicate_batch; from src.discovery.import_csv import CSVDiscovery; db = Database('data/database/leads.db'); leads, _ = CSVDiscovery().parse_csv('data/input/candidates_sample.csv'); to_ins, to_upd, stats = deduplicate_batch(db.get_all_leads(), leads); print(stats)"
   ```

   **Expected Output on Screen:**
   ```text
   {'total_incoming': 11, 'new_records': 0, 'merged_records': 0, 'exact_duplicates': 11}
   ```

2. **Verify Database Record Count Unchanged:**
   ```powershell
   python -c "from src.database import Database; db = Database('data/database/leads.db'); print(f'Total candidates in SQLite: {len(db.get_all_leads())}')"
   ```

   **Expected Output on Screen:**
   ```text
   Total candidates in SQLite: 11
   ```

3. **Narration & Talking Points:**
   > *"Notice the result: 11 incoming records, exactly 0 new records inserted, and 11 exact duplicates identified and suppressed.  
   > The database record count remains exactly 11.  
   > 
   > Our deduplication logic matches candidates by normalized platform key—lowercasing both platform and ID—and canonicalizes URLs by stripping session state, default ports, and tracking parameters like `utm_source`, `ref`, and YouTube `si` tokens.  
   > Furthermore, if an incoming record contains newer evidence links or upload dates, our deterministic merge updates the existing record non-destructively without creating a secondary duplicate row."*

---

### Segment 5: Deliverables Export & Grounded Outreach Preparation (5:15 – 6:30)

#### Objective
Export the production deliverables and CRM package, verify that synthetic fixtures never contaminate real lead exports, and demonstrate a Priority A grounded multi-channel outreach draft.

#### Visual / Interface
Navigate to **Tab 8: 📤 Production Data & CRM Sync**, then **Tab 5: ✉️ Outreach Studio & Copy**.

#### Actions & Demonstration Steps
1. **Demonstrate Production Isolation (Tab 8):**
   - Point to the checkbox:  
     `Include benchmark test fixtures in qualified export (Testing/inspection mode)` &rarr; **UNCHECKED (Default Production Mode)**.
   - Point to the banner:  
     `🛡️ Production isolation active: Benchmark fixtures excluded from production qualified_leads.csv.`
   - Click **"📦 Generate Complete Deliverables Package"**.
   - Switch to PowerShell and inspect `data/output/qualified_leads.csv`:

     ```powershell
     Get-Content data\output\qualified_leads.csv
     ```

     **Expected Output on Screen (Strictly 1 line - header only, 0 data rows):**
     ```text
     creator_name,creator_type,country,language,platform,platform_id,official_profile_url,candidate_source_url,recent_content_urls,recent_content_dates,commercial_evidence_url,workflow_need_evidence_url,business_contact_type,business_contact_value,business_contact_source_url,business_contact_last_active,evidence_checked_at,qualification_status,disqualification_reasons,score,priority,first_discovered_at,last_checked_at,last_run_id,is_synthetic
     ```
   - Explain: *"Because all 11 candidates in our database are synthetic validation fixtures, standard production export isolates them completely. Zero fake rows enter `qualified_leads.csv`."*

2. **Inspect Priority A Personalised Outreach Draft (Tab 5):**
   - Click **Tab 5: ✉️ Personalised Outreach Preparation**.
   - Select candidate: `[FIXTURE] The SaaS Breakout Show (UC_SAAS_BREAKOUT) [Priority A]`.
   - Show Left Column (Channel Suitability & Grounding):
     - **Chosen Primary Channel:** `email`  
       *Rationale: Dedicated public business inquiries inbox listed on channel.*
     - **Backup Channel:** `linkedin`  
       *Rationale: Host LinkedIn profile verified active.*
     - **Cited Content URL:** `https://youtube.com/watch?v=saas_ep42_full`
     - **Sender Identity:** `IncuBrix Growth Engineer Assessment Candidate` *(Honest disclosure; never claims to be an employee)*.
   - Show Right Column (3-Touch Sequence):
     - **Subject Line:** `Quick question regarding The SaaS Breakout Show`
     - **Touch 1 (Grounded Message):** Highlights specific recent episode `saas_ep42_full`, identifies the repurposing bottleneck, and suggests creating multi-format short assets.
     - **Touch 2 (+3 days delay):** Value-add follow-up offering a concrete repurposing sample.
     - **Touch 3 (+7 days delay):** Polite, clean breakup follow-up.
     - **Compliant Opt-Out Notice:** Displayed in all 3 touches (`If you'd prefer not to hear from me, just reply 'stop'`).
   - Reiterate Compliance Safeguard: *"No messages are dispatched to real creators. This copy is prepared strictly for manual CRM review."*

---

### Segment 6: Controlled Failure Recovery & Circuit Breakers (6:30 – 7:30)

#### Objective
Demonstrate how the system handles external failures: SSRF attacks, malformed CSV headers, and opt-out suppression.

#### Visual / Interface
Use **Tab 4 (SSRF Sandbox)** and the PowerShell terminal.

#### Actions & Demonstration Steps
1. **Demonstrate SSRF Protection Sandbox (Tab 4):**
   - Navigate to Tab 4, scroll down to **"🛡️ Safe URL Verification Sandbox"**.
   - Input: `http://169.254.169.254/latest/meta-data/` (AWS Cloud Metadata Service).
   - Click **"🔎 Audit URL Safety"**.
   - Expected Output on Screen:
     > `❌ Blocked URL: Blocked: IP 169.254.169.254 is within a restricted or link-local private network.`
   - Try input: `http://127.0.0.1:8501`.
   - Expected Output on Screen:
     > `❌ Blocked URL: Blocked: IP 127.0.0.1 is loopback/private.`
   - Explain: *"The evidence fetcher prevents Server-Side Request Forgery by resolving hostnames and blocking all private, loopback, and cloud metadata subnets before any HTTP request is dispatched."*

2. **Demonstrate Malformed CSV Header Rejection:**
   Run a quick one-liner parsing a broken CSV missing mandatory fields:

   ```powershell
   python -c "import io; from src.discovery.import_csv import CSVDiscovery; broken_csv = io.BytesIO(b'bad_header,another_col\nval1,val2\n'); leads, errs = CSVDiscovery().parse_csv(broken_csv); print('Errors caught cleanly:', errs)"
   ```

   **Expected Output on Screen:**
   ```text
   Errors caught cleanly: ["CSV missing mandatory columns: 'creator_name', 'official_profile_url', 'platform', 'platform_id'. Found: ['another_col', 'bad_header']"]
   ```
   - Explain: *"Malformed files are intercepted with explicit validation errors; they never corrupt database tables."*

3. **Demonstrate Opt-Out Suppression List:**
   ```powershell
   python -c "from src.verification.seed_testing import OutreachSimulator; OutreachSimulator.record_opt_out('test@creator.synthetic.test', channel='email'); print('Opt-out recorded in SQLite suppression_list table successfully.')"
   ```
   - Explain: *"When an opt-out event is received, the contact is recorded in the global `suppression_list` table. Future outreach drafts targeting this endpoint are permanently blocked."*

---

### Segment 7: Empirical Results, Scale Benchmarks & Boundaries (7:30 – 8:00)

#### Objective
Present verified test suite results, empirical performance benchmarks, and an honest declaration of current operational boundaries.

#### Visual / Interface
Terminal showing `pytest -v` and [`reports/scale_test_results.csv`](file:///c:/lead-generation/reports/scale_test_results.csv).

#### Actions & Demonstration Steps
1. **Execute Automated Test Suite in Terminal:**
   ```powershell
   pytest -v
   ```
   **Expected Output on Screen:**
   ```text
   ============================= 101 passed in 6.85s =============================
   ```
2. **Display Measured Scale Benchmark Results:**
   ```powershell
   Get-Content reports\scale_test_results.csv
   ```
   Highlight the empirical scale metrics:
   - **100 records:** 0.39s (256.7 rec/s), 2.59 MB RAM, 0 rows leaked.
   - **1,000 records:** 3.45s (289.8 rec/s), 24.07 MB RAM, 0 rows leaked.
   - **5,000 records:** 25.15s (198.8 rec/s), 119.92 MB RAM, 0 rows leaked.
3. **Closing Statement & Operational Boundaries:**
   > *"To conclude with honest engineering boundaries:  
   > - The test suite is 100% green across 101 unit, integration, and reliability tests.  
   > - The database currently holds 0 real qualified leads and 11 synthetic validation fixtures. We make no false claims of live production discovery or delivery.  
   > - Outreach simulation was validated against controlled seed accounts, not external transactional email servers.  
   > - Automated social DM bots and scraping are intentionally excluded for compliance.  
   > The engine is auditable, repeatable, and ready for controlled Week 1 operational pilot onboarding.  
   > Thank you."*

---

## Rehearsal Record & Empirical Verification Matrix

Every step in this runbook was rehearsed and verified against the live codebase:

| Step | Rehearsal Command / Action | Empirical Verification Result | Status |
| :---: | :--- | :--- | :---: |
| **1** | Directory structure inspection | Validated modular separation across `src/`, `data/`, `tests/`, `reports/`. | **VERIFIED** |
| **2** | `streamlit run app.py` | UI loaded at `http://localhost:8501`, metric cards displayed 11 candidates. | **VERIFIED** |
| **3** | Tab 3 & Tab 4 Gate Inspection | `UC_SAAS_BREAKOUT` passed 10 gates (88.0 pts); `UC_UNMONETIZED` flagged `needs_review`. | **VERIFIED** |
| **4** | Repeat CSV deduplication run | Ingested `candidates_sample.csv` twice: 0 new rows, 11 exact duplicates rejected. | **VERIFIED** |
| **5** | Deliverable export isolation | Ran `export_workbook_pack(allow_synthetic=False)`: `qualified_leads.csv` had strictly 0 rows. | **VERIFIED** |
| **6** | Priority A draft inspection | Verified honest sender identity, opt-out language, and recent video citation. | **VERIFIED** |
| **7** | SSRF protection sandbox | `http://169.254.169.254` and `http://127.0.0.1` blocked; public URLs permitted. | **VERIFIED** |
| **8** | Quota exhaustion handling | `YouTubeAPIDiscovery.smoke_test()` returned `configured: False` with diagnostic JSON. | **VERIFIED** |
| **9** | Automated test suite execution | `pytest -v` executed: **101 passed, 0 failed** in 6.85 seconds. | **VERIFIED** |
| **10**| Scale benchmarks execution | 100, 1,000, 5,000 records processed with 0 leaks in `reports/scale_test_results.csv`. | **VERIFIED** |
