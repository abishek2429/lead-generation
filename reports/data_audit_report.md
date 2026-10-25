# Current Data Counts and Integrity Audit Report
**IncuBrix Lead Generation & Outreach Engine**  
**Assessment Option 1: Multi-Channel Lead Generation & Outreach Engine**  
**Audit Timestamp:** 2026-10-25 18:35:00 UTC  
**Database File:** `data/database/leads.db`  
**Database Size:** 140.0 KB (SQLite 3 with WAL Mode)  

---

## 1. Executive Summary & Data Integrity Declaration

In accordance with strict assessment integrity guidelines:
- **Zero Real Creators Fabricated:** The repository does not fabricate real creators, fictitious contacts, fabricated engagement metrics, or synthetic followers.
- **Strict Synthetic Fixture Isolation:** All test and validation records are explicitly tagged with `is_synthetic = True` (or `is_synthetic = 1` in SQLite) and prefixed with `[FIXTURE]` or `[SYNTHETIC-BENCHMARK]`.
- **Production Export Guarantee:** Standard production exports (`allow_synthetic = False`) strictly filter out synthetic fixtures, guaranteeing **0 synthetic rows** in `qualified_leads.csv` and `priority_a_outreach.csv`.

---

## 2. Current Real vs. Synthetic Record Counts

Below is the verified record breakdown from the active database (`data/database/leads.db`):

| Category | Real Leads (`is_synthetic = 0`) | Synthetic Test Fixtures (`is_synthetic = 1`) | Total Records in Database | Status & Behavior Description |
| :--- | :---: | :---: | :---: | :--- |
| **Discovered / Unverified** | **0** | **0** | **0** | Newly discovered candidates awaiting gate evaluation. |
| **Needs Review** | **0** | **1** | **1** | Candidates with missing evidence URLs (commercial/workflow/contact). |
| **Qualified Leads** | **0** | **7** | **7** | Fully passed all 10 non-negotiable policy hard gates. |
| **Disqualified Leads** | **0** | **3** | **3** | Excluded due to agency segment, non-target country, or inactive content. |
| **Total Candidates** | **0** | **11** | **11** | All records currently stored in `leads.db`. |
| **Priority A Leads Prepared** | **0** | **7** | **7** | Top qualified leads prepared with 3-touch grounded outreach. |
| **Source-Linked Evidence Items** | **0** | **77** | **77** | 7 source-linked claims per candidate in `evidence_items`. |
| **Verification Audit Log Entries** | **0** | **11** | **11** | Immutable gate evaluation logs in `verification_logs`. |
| **Production Export Output** | **0 rows** | N/A | **0 rows** | `data/output/qualified_leads.csv` (Strict Production Mode). |

---

## 3. Detailed Audit of Synthetic Test Fixtures (`candidates_sample.csv`)

The 11 test records in `data/input/candidates_sample.csv` were imported to rigorously validate the 10 qualification hard gates:

### Qualified Fixtures (7 records):
1. **[FIXTURE] The SaaS Breakout Show** (`UC_SAAS_BREAKOUT`) — US, Video Podcaster, Passed all 10 gates.
2. **[FIXTURE] Fintech Horizons Podcast** (`UC_FINTECH_HORIZONS`) — UK, Podcaster, Passed all 10 gates.
3. **[FIXTURE] Growth Architect Daily** (`UC_GROWTH_ARCHITECT`) — Canada, Coach Creator, Passed all 10 gates.
4. **[FIXTURE] Sydney Tech & AI Weekly** (`UC_SYDNEY_TECH_AI`) — Australia, Video Creator, Passed all 10 gates.
5. **[FIXTURE] Dublin Product Leaders** (`UC_DUBLIN_PROD`) — Ireland, Consultant Creator, Passed all 10 gates.
6. **[FIXTURE] Auckland Founder Journey** (`UC_AKL_FOUNDER`) — New Zealand, Educator Creator, Passed all 10 gates.
7. **[FIXTURE] LionCity Tech Bytes** (`UC_SG_TECHBYTES`) — Singapore, Podcaster, Passed all 10 gates.

### Disqualified Fixtures (3 records):
1. **[FIXTURE] Apex Media Growth Agency** (`UC_APEX_MEDIA_AGY`) — **Disqualified by Gate 1 (Segment Gate)**: Excluded creator type `'agency'`.
2. **[FIXTURE] Berlin Creator Lounge** (`UC_BERLIN_CREATOR`) — **Disqualified by Gate 2 (Country Gate)**: Country `'Germany'` is outside the 7 approved target geographies.
3. **[FIXTURE] Inactive Podcaster Channel** (`UC_INACTIVE_POD`) — **Disqualified by Gate 9 (Activity Gate)**: Latest content publication date is older than 60 days (inactive).

### Needs Review Fixtures (1 record):
1. **[FIXTURE] Unmonetized Tech Enthusiast** (`UC_UNMONETIZED`) — **Flagged for Review by Gate 5 & Gate 6**: Missing commercial monetization URL and missing workflow need evidence URL.

---

## 4. Benchmark Performance Fixtures Summary

In addition to the 11 baseline validation fixtures, the engine maintains isolated synthetic benchmark datasets in `data/benchmarks/`:

- `data/benchmarks/benchmark_100.csv`: 100 synthetic performance records (63 KB).
- `data/benchmarks/benchmark_1000.csv`: 1,000 synthetic performance records (627 KB).
- `data/benchmarks/benchmark_5000.csv`: 5,000 synthetic performance records (3.13 MB).

These fixtures are executed exclusively in dedicated benchmark runner databases (`data/database/benchmark_{size}.db`) during performance profiling and never enter production tables.
